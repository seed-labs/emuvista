/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandData;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingPaymentCommandRepository;
import org.apache.fineract.consumer.openbanking.command.service.OpenBankingPaymentCommandServiceImpl;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class CustomerCardPaymentsController {
    private final BankCardService cards;
    private final OpenBankingPaymentCommandRepository payments;

    @GetMapping("/api/v1/card-payments")
    public List<OpenBankingPaymentCommandData> history(@AuthenticationPrincipal Jwt jwt) {
        var accounts = cards.ownCards(jwt).stream().map(BankCardService.CustomerCardData::accountId).distinct().toList();
        return payments.findByFromAccountIdInOrderByCreatedAtDesc(accounts).stream()
                .map(OpenBankingPaymentCommandServiceImpl::acknowledgement).toList();
    }
}
