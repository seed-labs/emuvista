/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.exception;

import org.apache.fineract.consumer.infrastructure.exception.AbstractConsumerException;
import org.springframework.http.HttpStatus;

public class OpenBankingPaymentInvalidException extends AbstractConsumerException {
    public static final String CODE = "error.msg.consumer.openbanking.payment.invalid";

    public OpenBankingPaymentInvalidException() {
        super(HttpStatus.CONFLICT, CODE, "Payment currency, account or request identifier is invalid");
    }
}
