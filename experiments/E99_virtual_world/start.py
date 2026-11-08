#!/usr/bin/env python3
"""Start infrastructure, verify it, then opt in to the resident containers."""

import argparse
import json
from pathlib import Path
import subprocess
import time

HERE=Path(__file__).resolve().parent


class Startup:
    def __init__(self, output, timeout=900):
        self.output=Path(output).resolve()
        self.plan=json.loads((self.output/'startup.json').read_text())
        self.timeout=timeout

    def compose(self,*arguments,timeout=120):
        result=subprocess.run(['docker','compose',*arguments],cwd=self.output,
                              text=True,capture_output=True,timeout=timeout,stdin=subprocess.DEVNULL)
        if result.returncode:
            raise RuntimeError(result.stderr.strip()[-1200:] or 'Docker Compose failed')
        return result.stdout

    def status(self):
        raw=self.compose('ps','--all','--format','json')
        try:
            rows=json.loads(raw or '[]')
            if isinstance(rows,dict):rows=[rows]
        except ValueError:
            rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
        return {row['Service']:row for row in rows}

    def pending(self, rows):
        pending=[]
        for name in self.plan['infrastructure']:
            row=rows.get(name,{})
            state=row.get('State','not_created')
            if name in self.plan['initializers']:
                if state=='exited':
                    if row.get('ExitCode')!=0:
                        raise RuntimeError(name+' failed; inspect its Compose logs before starting residents')
                else:pending.append(name)
            elif state!='running' or row.get('Health','') not in ('','healthy'):
                if state in ('exited','dead'):
                    raise RuntimeError(name+' stopped; inspect its Compose logs before starting residents')
                pending.append(name)
        return pending

    def network_ready(self):
        probe=self.plan['probe']
        self.compose('exec','-T',probe,'mkdir','-p','/tmp/emuvista-ready')
        for name,service in self.plan['services'].items():
            certificate=self.output/'world-certs'/(name+'.pem')
            target='/tmp/emuvista-ready/'+name+'.pem'
            self.compose('cp',str(certificate),probe+':'+target)
            self.compose('exec','-T',probe,'curl','--fail','--silent','--show-error','--max-time','8',
                         '--cacert',target,service['url'],timeout=12)
        hostname=self.plan['services']['email']['hostname']
        for port in (587,993):
            command=['exec','-T',probe,'timeout','10','openssl','s_client','-brief',
                     '-connect',hostname+':'+str(port),'-servername',hostname,
                     '-verify_hostname',hostname,'-verify_return_error','-CAfile','/tmp/emuvista-ready/email.pem']
            if port==587:command.extend(['-starttls','smtp'])
            self.compose(*command,timeout=15)

    def wait(self):
        deadline=time.monotonic()+self.timeout
        while True:
            pending=self.pending(self.status())
            if not pending:
                try:
                    self.network_ready()
                    print('Infrastructure ready: initializers completed, services healthy, HTTPS/SMTP/IMAP verified from AS171.',flush=True)
                    return
                except (RuntimeError,subprocess.TimeoutExpired) as error:
                    message='Waiting for simulated-network reachability: '+str(error)[:250]
            else:message='Waiting for infrastructure: '+', '.join(pending)
            if time.monotonic()>=deadline:
                raise RuntimeError('Infrastructure readiness timed out. No residents were started. '+message)
            print(message,flush=True)
            time.sleep(min(5,max(0,deadline-time.monotonic())))

    def run(self, infrastructure_only=False, agents_only=False):
        rows=self.status()
        active=[name for name in self.plan['agents'] if rows.get(name,{}).get('State')=='running']
        if active:
            raise RuntimeError('Residents are already running. Stop their containers before a staged restart: '+', '.join(active))
        if not agents_only:
            print('Starting infrastructure; resident containers remain disabled.',flush=True)
            self.compose('up','-d','--no-build','--pull','never',timeout=self.timeout)
        self.wait()
        if not infrastructure_only:
            print('Starting residents after successful readiness checks.',flush=True)
            self.compose('--profile','agents','up','-d','--no-build','--pull','never','--no-deps',*self.plan['agents'],timeout=120)
        else:print('Residents remain stopped. Start them with: python3 start.py --agents-only',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'output')
    parser.add_argument('--timeout',type=int,default=900)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--infrastructure-only',action='store_true')
    group.add_argument('--agents-only',action='store_true')
    args=parser.parse_args()
    if args.timeout<1:parser.error('timeout must be positive')
    try:Startup(args.output,args.timeout).run(args.infrastructure_only,args.agents_only)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
