/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.YearMonth;
import java.util.Set;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.ObjectMapper;

@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "consumer.cards.config")
public class BankCardBootstrap implements ApplicationRunner {
    private final BankCardRepository cards;
    private final ObjectMapper mapper;
    @Value("${consumer.cards.config}") private String config;

    public record Spec(String id, String number, String name, String account, String email,
            String currency, String status, String expires) { }

    @Override
    @Transactional
    public void run(ApplicationArguments args) throws Exception {
        Spec[] specs = mapper.readValue(Files.readString(Path.of(config)), Spec[].class);
        for (Spec spec : specs) {
            if (!BankCard.validNumber(spec.number()) || !Set.of("active", "blocked").contains(spec.status())) {
                throw new IllegalStateException("Invalid simulated debit card configuration");
            }
            UUID id = UUID.nameUUIDFromBytes(spec.id().getBytes(StandardCharsets.UTF_8));
            var existing = cards.findById(id);
            if (existing.isPresent()) {
                BankCard card = existing.get();
                if (!card.getCardNumber().equals(spec.number())
                        || !card.getAccountExternalId().equals(spec.account())
                        || !card.getOwnerEmail().equals(spec.email())) {
                    throw new IllegalStateException("Saved card differs from initial configuration");
                }
                continue;
            }
            cards.save(BankCard.create(id, spec.number(), spec.name(), spec.account(), spec.email(),
                    spec.currency(), spec.status(), YearMonth.parse(spec.expires()).atEndOfMonth()));
        }
    }
}
