/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.service;

import java.util.UUID;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandData;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandRequest;
import org.springframework.security.oauth2.jwt.Jwt;

public interface OpenBankingPaymentCommandService {
    OpenBankingPaymentCommandData debit(Jwt jwt, UUID requestId, OpenBankingPaymentCommandRequest request);
    OpenBankingPaymentCommandData status(Jwt jwt, UUID requestId);
}
