/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.opening;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.web.data.PasswordPolicy;
import org.apache.fineract.consumer.registration.command.data.SubmitRegistrationCommandData;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
public class CustomerOpeningController {
    private final CustomerOpeningService service;
    public record Registration(@NotBlank @Size(max=50) String firstName, @NotBlank @Size(max=50) String lastName,
            @NotBlank @Email String email,
            @NotBlank @Size(min=PasswordPolicy.MIN_LENGTH,max=PasswordPolicy.MAX_LENGTH)
            @Pattern(regexp=PasswordPolicy.COMPLEXITY_PATTERN) String password) { }
    public record Account(@NotNull @Positive Long productId, @NotNull UUID id) { }

    @PostMapping("/api/v1/registration/open")
    public SubmitRegistrationCommandData register(@Valid @RequestBody Registration request) {
        return service.register(request.firstName(), request.lastName(), request.email(), request.password());
    }
    @GetMapping("/api/v1/customer-accounts/products")
    public List<Map<String, Object>> products(@AuthenticationPrincipal Jwt jwt) { return service.products(jwt); }
    @PostMapping("/api/v1/customer-accounts")
    public Map<String, Object> open(@AuthenticationPrincipal Jwt jwt, @Valid @RequestBody Account request) {
        return service.open(jwt, request.productId(), request.id());
    }
}
