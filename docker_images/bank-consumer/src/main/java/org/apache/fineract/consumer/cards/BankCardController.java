/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class BankCardController {
    private final BankCardService service;
    public record Request(@NotBlank @Pattern(regexp = "[0-9]{16,19}") String cardNumber,
            @NotBlank @Email String walletOwnerEmail) { }

    @PostMapping("/api/v1/openbanking/account-access-consents/cards")
    public BankCardService.ConsentData begin(@AuthenticationPrincipal Jwt jwt, @Valid @RequestBody Request request) {
        return service.begin(jwt, request.cardNumber(), request.walletOwnerEmail());
    }

    @GetMapping("/api/v1/openbanking/cards/current")
    public BankCardService.CardData current(@AuthenticationPrincipal Jwt jwt) { return service.current(jwt); }

    @PostMapping("/api/v1/openbanking/cards/current/revoke")
    public Map<String, String> revoke(@AuthenticationPrincipal Jwt jwt) {
        service.revoke(jwt);
        return Map.of("status", "revoked");
    }
}
