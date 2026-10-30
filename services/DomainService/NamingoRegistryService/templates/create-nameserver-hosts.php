<?php
/** Seed the hosted nameservers using the Registry panel's host record structure. */
declare(strict_types=1);

/** Both hosts succeed together; existing records are checked, never overwritten. */
function initializeHostedNameservers(PDO $db, array $hosts, string $registrar, bool $checkOnly): array
{
    $parent = getenv('REGISTRY_PARENT_DOMAIN');
    if (!is_string($parent) || !preg_match('/^[a-z0-9-]+\.[a-z0-9-]+$/D', $parent)) {
        throw new RuntimeException('Invalid hosting parent domain');
    }
    if ($checkOnly) {
        $db->exec('SET TRANSACTION READ ONLY');
    }
    $db->beginTransaction();
    try {
        $find = $db->prepare('SELECT id FROM registrar WHERE clid = ?');
        $find->execute([$registrar]);
        $registrarId = $find->fetchColumn();
        if ($registrarId === false) {
            throw new RuntimeException("Registrar $registrar 不存在；请先完成 Registry 启动初始化。");
        }
        $find = $db->prepare('SELECT id, clid FROM domain WHERE name = ?'
            . ($checkOnly ? '' : ' FOR UPDATE'));
        $find->execute([$parent]);
        $domain = $find->fetch(PDO::FETCH_ASSOC);
        if (!$domain) {
            throw new RuntimeException("$parent 域名对象不存在；请检查 Registry 启动时的域名初始化。");
        }
        if ((int)$domain['clid'] !== (int)$registrarId) {
            throw new RuntimeException("$parent 不属于 Registrar {$registrar}，拒绝创建 host。");
        }

        $findHost = $db->prepare('SELECT id, domain_id, clid FROM host WHERE name = ?'
            . ($checkOnly ? '' : ' FOR UPDATE'));
        $findAddress = $db->prepare("SELECT addr FROM host_addr WHERE host_id = ? AND ip = 'v4'");
        $findStatus = $db->prepare('SELECT status FROM host_status WHERE host_id = ?');
        $messages = [];
        foreach ($hosts as [$name, $address]) {
            if (!preg_match('/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.' . preg_quote($parent, '/') . '$/D', $name)) {
                throw new RuntimeException("非法的托管 host 名称：$name");
            }
            // Matches HostsController::createHost: IPv4 syntax, including private addresses.
            if (!filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
                throw new RuntimeException("$name 的 IPv4 地址无效：$address");
            }
            $findHost->execute([$name]);
            $host = $findHost->fetch(PDO::FETCH_ASSOC);
            if ($host) {
                if ((int)$host['clid'] !== (int)$registrarId
                    || (int)$host['domain_id'] !== (int)$domain['id']) {
                    throw new RuntimeException("$name 的 Registrar 或父域名归属不一致，保留原记录。");
                }
                $findAddress->execute([$host['id']]);
                $addresses = $findAddress->fetchAll(PDO::FETCH_COLUMN);
                if (!in_array($address, $addresses, true)) {
                    throw new RuntimeException("$name 已存在，但没有 IPv4 {$address}；现有 IPv4："
                        . implode(', ', $addresses) . '。保留原记录，请在 Registry 前端核对。');
                }
                $findStatus->execute([$host['id']]);
                $statuses = $findStatus->fetchAll(PDO::FETCH_COLUMN);
                if (!$statuses || in_array('pendingDelete', $statuses, true)) {
                    throw new RuntimeException("$name 缺少状态或正在删除，请在 Registry 前端核对。");
                }
                $messages[] = "PASS $name $address 已存在，归属、地址和状态已核对。";
                continue;
            }
            if ($checkOnly) {
                throw new RuntimeException("$name 尚未登记；请检查 Registry 的 NS 启动初始化日志。");
            }
            $db->prepare('INSERT INTO host (name, domain_id, clid, crid, crdate)'
                . ' VALUES (?, ?, ?, ?, NOW(3))')
                ->execute([$name, $domain['id'], $registrarId, $registrarId]);
            $hostId = $db->lastInsertId();
            $db->prepare("INSERT INTO host_addr (host_id, addr, ip) VALUES (?, ?, 'v4')")
                ->execute([$hostId, $address]);
            $db->prepare("INSERT INTO host_status (host_id, status) VALUES (?, 'ok')")
                ->execute([$hostId]);
            $messages[] = "PASS $name $address 已创建，归属 Registrar {$registrar}。";
        }
        $db->commit();
        return $messages;
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $error;
    }
}

try {
    $path = '/opt/registry/epp/config.php';
    if (!is_file($path)) {
        throw new RuntimeException('找不到 Registry 数据库配置；--container 必须指定 NamingoRegistryService 容器。');
    }
    $config = require $path;
    $db = new PDO(
        'mysql:host=' . $config['db_host'] . ';dbname=registry;charset=utf8mb4',
        $config['db_username'], $config['db_password'],
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );
    $hosts = json_decode(getenv('REGISTRY_NAMESERVER_HOSTS'), true, 512, JSON_THROW_ON_ERROR);
    $messages = initializeHostedNameservers(
        $db, $hosts, getenv('REGISTRY_EPP_USERNAME'), getenv('REGISTRY_CHECK_ONLY') === '1'
    );
    echo implode("\n", $messages) . "\n";
} catch (Throwable $error) {
    fwrite(STDERR, 'FAIL: ' . $error->getMessage() . "\n");
    exit(1);
}
