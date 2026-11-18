<?php
if (empty(em_shop_config()['mail'])) return;
require_once ABSPATH . WPINC . '/PHPMailer/Exception.php';
require_once ABSPATH . WPINC . '/PHPMailer/PHPMailer.php';
require_once ABSPATH . WPINC . '/PHPMailer/SMTP.php';
for ($attempt = 0; $attempt < 120; $attempt++) {
    $mailer = new \PHPMailer\PHPMailer\PHPMailer(true);
    do_action('phpmailer_init', $mailer);
    $mailer->Timeout = 5;
    try {
        if ($mailer->smtpConnect()) {
            $mailer->smtpClose();
            return;
        }
    } catch (\PHPMailer\PHPMailer\Exception $error) {
        // The partner may still be creating its sender mailbox.
    }
    sleep(5);
}
throw new Exception('Partner mailbox is not ready');
