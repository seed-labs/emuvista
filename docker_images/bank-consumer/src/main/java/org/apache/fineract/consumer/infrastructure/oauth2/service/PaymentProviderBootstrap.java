/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.infrastructure.oauth2.service;

import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.oauth2.domain.RegisteredTpp;
import org.apache.fineract.consumer.infrastructure.oauth2.repository.RegisteredTppRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Register a configured provider, never bind any customer's bank accounts. */
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(name = "consumer.payments.client-id")
public class PaymentProviderBootstrap implements ApplicationRunner {
    private final RegisteredTppRepository repository;
    private final PasswordEncoder passwordEncoder;
    @Value("${consumer.payments.client-id}") private String clientId;
    @Value("${consumer.payments.client-secret}") private String clientSecret;
    @Value("${consumer.payments.redirect-uris}") private String redirectUris;

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        var existing = repository.findByClientId(clientId);
        if (existing.isPresent()) {
            if (!passwordEncoder.matches(clientSecret, existing.get().getClientSecretHash())
                    || !redirectUris.equals(existing.get().getRedirectUri())) {
                throw new IllegalStateException("Configured payment provider differs from saved bank state");
            }
        } else {
            repository.save(RegisteredTpp.onboard(UUID.randomUUID(), clientId, passwordEncoder.encode(clientSecret),
                    "Payment wallet", redirectUris,
                    "openbanking:consents,openbanking:accounts.read,openbanking:cards.read,openbanking:payments"));
        }
    }
}
