/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.api;

import jakarta.validation.Valid;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.web.data.ConsumerHeaders;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandData;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandRequest;
import org.apache.fineract.consumer.openbanking.command.service.OpenBankingPaymentCommandService;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/openbanking/payments")
@RequiredArgsConstructor
public class OpenBankingPaymentCommandController {
    private final OpenBankingPaymentCommandService service;

    @PostMapping
    public OpenBankingPaymentCommandData debit(@AuthenticationPrincipal Jwt jwt,
            @RequestHeader(ConsumerHeaders.IDEMPOTENCY_KEY) UUID requestId,
            @Valid @RequestBody OpenBankingPaymentCommandRequest request) {
        return service.debit(jwt, requestId, request);
    }
}
