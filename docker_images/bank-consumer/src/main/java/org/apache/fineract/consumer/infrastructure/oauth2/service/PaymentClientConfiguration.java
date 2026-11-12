/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.infrastructure.oauth2.service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/** Independent credentials and callbacks per payment partner. */
@Component
public class PaymentClientConfiguration {
    public record Client(String clientId, String clientSecret, List<String> redirectURIs) {
        public String platform() {
            var uri = java.net.URI.create(redirectURIs.getFirst());
            return uri.getScheme()+"://"+uri.getAuthority();
        }
    }

    private final Map<String, Client> clients = new LinkedHashMap<>();

    public PaymentClientConfiguration(ObjectMapper mapper,
            @Value("${consumer.payments.clients-config:}") String config,
            @Value("${consumer.payments.client-id:}") String clientId,
            @Value("${consumer.payments.client-secret:}") String secret,
            @Value("${consumer.payments.redirect-uris:}") String redirects) throws IOException {
        List<Client> configured = List.of();
        if (!config.isBlank()) {
            configured = Arrays.asList(mapper.readValue(Files.readString(Path.of(config)), Client[].class));
        } else if (!clientId.isBlank()) {
            configured = List.of(new Client(clientId, secret, Arrays.asList(redirects.split(","))));
        }
        for (Client client : configured) {
            if (client.clientId() == null || client.clientId().isBlank() || client.clientSecret() == null
                    || client.clientSecret().isBlank() || client.redirectURIs() == null || client.redirectURIs().isEmpty()
                    || clients.putIfAbsent(client.clientId(), client) != null) {
                throw new IllegalStateException("Invalid or duplicate payment partner configuration");
            }
        }
    }

    public Collection<Client> getClients() {
        return List.copyOf(clients.values());
    }

    public Client find(String clientId) {
        return clients.get(clientId);
    }
}
