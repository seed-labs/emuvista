/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.oauth2.service.OAuth2ConsentIdExtractor;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.server.authorization.OAuth2TokenType;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.authorization.OAuth2AuthorizationService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class BankCardAuthorizationController {
    private final OAuth2AuthorizationService authorizations;
    private final BankCardService cards;

    @GetMapping("/api/v1/cards/authorization")
    public BankCardService.CardData preview(@AuthenticationPrincipal Jwt jwt, @RequestParam String state) {
        var authorization = authorizations.findByToken(state, new OAuth2TokenType("state"));
        if (authorization == null || !jwt.getSubject().equals(authorization.getPrincipalName())) {
            throw new AccessDeniedException("Card authorization session was not found");
        }
        return cards.preview(OAuth2ConsentIdExtractor.consentIdOf(authorization), UUID.fromString(jwt.getSubject()));
    }
}
