/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.ZoneOffset;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.fineractclient.service.CustomerOpeningClient;
import org.apache.fineract.consumer.opening.CustomerOpeningService;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class CardIssuanceController {
    private final CustomerOpeningService opening;
    private final CustomerOpeningClient core;
    private final BankCardRepository cards;
    private final BankCardService service;
    private final SecureRandom random = new SecureRandom();
    public record Request(@NotNull @Positive Long accountId, @NotNull UUID id) { }

    @PostMapping("/api/v1/cards")
    public synchronized BankCardService.CustomerCardData issue(@AuthenticationPrincipal Jwt jwt, @Valid @RequestBody Request request) {
        var user = opening.customer(jwt);
        var account = opening.ownAccount(jwt, request.accountId());
        UUID id = UUID.nameUUIDFromBytes((user.getPublicId()+":card:"+request.id()).getBytes(StandardCharsets.UTF_8));
        var existing = cards.findById(id);
        String reference = (String) account.get("externalId");
        if (reference == null || reference.isBlank()) {
            reference = "card-account-"+request.accountId();
            core.updateAccount(request.accountId(), Map.of("externalId", reference));
        }
        if (existing.isPresent()) {
            if (!reference.equals(existing.get().getAccountExternalId())
                    || !user.getEmail().equalsIgnoreCase(existing.get().getOwnerEmail())) {
                throw new AccessDeniedException("Request ID belongs to another card application");
            }
        } else {
            String currency = (String) ((Map<?, ?>) account.get("currency")).get("code");
            String number;
            do { number = nextNumber(); } while (cards.findByCardNumber(number).isPresent());
            cards.saveAndFlush(BankCard.create(id, number, currency+" debit card", reference,
                    user.getEmail(), currency, "active", java.time.YearMonth.now(ZoneOffset.UTC).plusYears(5).atEndOfMonth()));
        }
        return service.ownCards(jwt).stream().filter(card -> card.cardId().equals(id)).findFirst().orElseThrow();
    }

    private String nextNumber() {
        String base = String.format(Locale.ROOT, "99%013d", random.nextLong(10_000_000_000_000L));
        for (int digit=0; digit<10; digit++) if (BankCard.validNumber(base+digit)) return base+digit;
        throw new IllegalStateException("Card number generation failed");
    }
}
