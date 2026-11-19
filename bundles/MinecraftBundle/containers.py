"""Application container images retain SEED routes on both Alpine and Debian bases."""
from seedemu.containerBundle.ContainerBundle import PreparedContainer


class RoutedContainer(PreparedContainer):
    def _generateDockerfile(self):
        # Bundle.install may replace labels after joinInternalNetwork.
        labels = self._service.setdefault('labels', {})
        for index, network in enumerate(self._internal_networks):
            prefix = 'org.seedsecuritylabs.seedemu.meta.'
            labels.update({prefix + 'asn': str(network['asn']),
                           prefix + 'nodename': self.getHostname(),
                           prefix + 'role': 'Host',
                           prefix + f'net.{index}.name': network['network_name'],
                           prefix + f'net.{index}.address': network['ip_address']})
        dockerfile = super()._generateDockerfile()
        return dockerfile.replace(
            'RUN apt-get update && apt-get install -y --no-install-recommends '
            'iproute2 iputils-ping && rm -rf /var/lib/apt/lists/*',
            'RUN if command -v apk >/dev/null 2>&1; then apk add --no-cache iproute2 iputils; '
            'elif command -v apt-get >/dev/null 2>&1; then '
            'apt-get -o Acquire::Retries=3 update && '
            'apt-get -o Acquire::Retries=3 install -y --no-install-recommends iproute2 iputils-ping '
            '&& rm -rf /var/lib/apt/lists/*; else command -v ip; fi')
