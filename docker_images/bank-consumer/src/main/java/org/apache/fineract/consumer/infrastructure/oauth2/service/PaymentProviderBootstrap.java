/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.infrastructure.oauth2.service;

import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.oauth2.domain.RegisteredTpp;
import org.apache.fineract.consumer.infrastructure.oauth2.repository.RegisteredTppRepository;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/** Register configured partners, never bind any customer's bank accounts. */
@Component
@RequiredArgsConstructor
public class PaymentProviderBootstrap implements ApplicationRunner {
    private final RegisteredTppRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final PaymentClientConfiguration configuration;

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        for (var client : configuration.getClients()) {
            register(client);
        }
    }

    private void register(PaymentClientConfiguration.Client client) {
        String clientId = client.clientId();
        String clientSecret = client.clientSecret();
        String redirectUris = String.join(",", client.redirectURIs());
        var existing = repository.findByClientId(clientId);
        if (existing.isPresent()) {
            if (!passwordEncoder.matches(clientSecret, existing.get().getClientSecretHash())
                    || !redirectUris.equals(existing.get().getRedirectUri())) {
                throw new IllegalStateException("Configured payment provider differs from saved bank state");
            }
        } else {
            repository.save(RegisteredTpp.onboard(UUID.randomUUID(), clientId, passwordEncoder.encode(clientSecret),
                    clientId, redirectUris,
                    "openbanking:consents,openbanking:accounts.read,openbanking:cards.read,openbanking:payments"));
        }
    }
}
