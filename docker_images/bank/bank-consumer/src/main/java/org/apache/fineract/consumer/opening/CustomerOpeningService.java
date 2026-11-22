/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.opening;

import feign.FeignException;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.access.service.AccessPolicyEvaluator;
import org.apache.fineract.consumer.infrastructure.access.service.OwnedAccountsCache;
import org.apache.fineract.consumer.infrastructure.fineractclient.service.CustomerOpeningClient;
import org.apache.fineract.consumer.registration.command.data.SubmitRegistrationCommandData;
import org.apache.fineract.consumer.user.command.data.CreateUserCommand;
import org.apache.fineract.consumer.user.command.data.UserStatus;
import org.apache.fineract.consumer.user.command.domain.User;
import org.apache.fineract.consumer.user.command.repository.UserCommandRepository;
import org.apache.fineract.consumer.user.command.service.UserCommandService;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class CustomerOpeningService {
    private final CustomerOpeningClient core;
    private final UserCommandService users;
    private final UserCommandRepository repository;
    private final PasswordEncoder passwords;
    private final OwnedAccountsCache ownership;

    /** Registration creates a new customer, never claims an existing customer's identity. */
    public synchronized SubmitRegistrationCommandData register(String first, String last, String email, String password) {
        email = email.trim().toLowerCase(java.util.Locale.ROOT);
        var previous = repository.findByEmail(email);
        if (previous.isPresent()) {
            var user = previous.get();
            if (user.getStatus() == UserStatus.PENDING_OTP && passwords.matches(password, user.getPasswordHash())) {
                return registration(user.getPublicId());
            }
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Registration is not available for this email");
        }
        // A stable, bank-local reference lets a lost core response be reconciled on retry.
        String reference = reference("customer:" + email);
        Map<String, Object> client;
        try { client = core.client(reference); }
        catch (FeignException.NotFound missing) {
            var created = core.createClient(Map.of("officeId", 1, "firstname", first.trim(), "lastname", last.trim(),
                    "externalId", reference, "legalFormId", 1, "active", true,
                    "activationDate", today(), "dateFormat", "yyyy-MM-dd", "locale", "en"));
            client = Map.of("id", created.get("resourceId"));
        }
        var created = users.create(CreateUserCommand.builder().email(email).passwordHash(passwords.encode(password))
                .fineractClientId(number(client, "id")).build());
        return registration(created.getPublicId());
    }

    private SubmitRegistrationCommandData registration(UUID id) {
        return SubmitRegistrationCommandData.builder().registrationId(id).status(UserStatus.PENDING_OTP).build();
    }

    public User customer(Jwt jwt) {
        if (!AccessPolicyEvaluator.hasScope(jwt, "consumer:full")) throw new AccessDeniedException("Customer login required");
        var user = repository.findByPublicId(UUID.fromString(jwt.getSubject()))
                .orElseThrow(() -> new AccessDeniedException("Customer login required"));
        if (user.getStatus() != UserStatus.BOUND) throw new AccessDeniedException("Verify your email first");
        return user;
    }

    public List<Map<String, Object>> products(Jwt jwt) {
        customer(jwt);
        return core.products().stream().map(p -> Map.<String,Object>of("id", p.get("id"), "name", p.get("name"),
                "currency", p.get("currency"))).toList();
    }

    /** Open an empty account for the signed-in person. No opening deposit is made. */
    public synchronized Map<String, Object> open(Jwt jwt, Long productId, UUID requestId) {
        var user = customer(jwt);
        String reference = reference(user.getPublicId() + ":account:" + requestId);
        Map<String, Object> account;
        try { account = core.accountByReference(reference); }
        catch (FeignException.NotFound missing) {
            if (core.products().stream().noneMatch(p -> productId.equals(number(p, "id")))) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Unknown savings product");
            }
            core.createAccount(Map.of("clientId", user.getFineractClientId(), "productId", productId,
                    "externalId", reference, "submittedOnDate", today(), "dateFormat", "yyyy-MM-dd", "locale", "en"));
            account = core.accountByReference(reference);
        }
        if (!user.getFineractClientId().equals(number(account, "clientId"))
                || !productId.equals(number(account, "savingsProductId"))) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Request ID belongs to another account application");
        }
        Long id = number(account, "id");
        var status = (Map<?, ?>) account.get("status");
        if (Boolean.TRUE.equals(status.get("submittedAndPendingApproval"))) {
            core.accountCommand(id, "approve", Map.of("approvedOnDate", today(), "dateFormat", "yyyy-MM-dd", "locale", "en"));
            account = core.account(id);
            status = (Map<?, ?>) account.get("status");
        }
        if (Boolean.TRUE.equals(status.get("approved"))) {
            core.accountCommand(id, "activate", Map.of("activatedOnDate", today(), "dateFormat", "yyyy-MM-dd", "locale", "en"));
            account = core.account(id);
        }
        ownership.evict(user.getFineractClientId());
        return account;
    }

    public Map<String, Object> ownAccount(Jwt jwt, Long id) {
        var user = customer(jwt);
        var account = core.account(id);
        if (!user.getFineractClientId().equals(number(account, "clientId"))) throw new AccessDeniedException("Account belongs to another customer");
        if (!Boolean.TRUE.equals(((Map<?, ?>) account.get("status")).get("active"))) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "An active account is required");
        }
        return account;
    }

    private static String reference(String input) {
        return "online-" + UUID.nameUUIDFromBytes(input.getBytes(StandardCharsets.UTF_8));
    }
    public static Long number(Map<String, Object> object, String key) { return ((Number) object.get(key)).longValue(); }
    private static String today() { return LocalDate.now(ZoneOffset.UTC).toString(); }
}
