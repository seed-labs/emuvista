/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.access.data.ConsumerAction;
import org.apache.fineract.consumer.infrastructure.access.service.AccessPolicyEvaluator;
import org.apache.fineract.consumer.infrastructure.configs.OAuth2ConsumerProperties;
import org.apache.fineract.consumer.infrastructure.fineractclient.generated.model.SavingsAccountData;
import org.apache.fineract.consumer.infrastructure.fineractclient.service.TransferFineractClient;
import org.apache.fineract.consumer.infrastructure.oauth2.data.OAuth2Constants;
import org.apache.fineract.consumer.openbanking.command.data.ConsentStatus;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPermission;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingConsent;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingConsentCommandRepository;
import org.apache.fineract.consumer.user.command.repository.UserCommandRepository;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class BankCardService {
    public static final String READ_SCOPE = "openbanking:cards.read";
    private final BankCardRepository cards;
    private final OpenBankingConsentCommandRepository consents;
    private final UserCommandRepository users;
    private final TransferFineractClient core;
    private final AccessPolicyEvaluator policy;
    private final OAuth2ConsumerProperties properties;

    public record CardData(UUID cardId, String name, String maskedCard, String currency, long balanceMinor) { }
    public record ConsentData(UUID consentId, UUID cardId, String name, String maskedCard, String currency) { }

    public record CustomerCardData(UUID cardId, String name, String number, String currency,
            String status, LocalDate expiresOn, long accountId, String accountNumber,
            String accountExternalId, long balanceMinor) { }

    /** Full card numbers are available only to the authenticated bank customer. */
    public List<CustomerCardData> ownCards(Jwt jwt) {
        if (!AccessPolicyEvaluator.hasScope(jwt, "consumer:full")) throw denied();
        UUID userId;
        try { userId = UUID.fromString(jwt.getSubject()); }
        catch (IllegalArgumentException | NullPointerException error) { throw denied(); }
        var user = users.findByPublicId(userId).orElseThrow(BankCardService::denied);
        if (user.getStatus() != org.apache.fineract.consumer.user.command.data.UserStatus.BOUND) throw denied();
        var accounts = new HashMap<String, SavingsAccountData>();
        return cards.findByOwnerEmailIgnoreCaseOrderByNameAsc(user.getEmail()).stream().map(card -> {
            var account = accounts.computeIfAbsent(card.getAccountExternalId(), core::retrieveSavingsAccountByExternalId);
            if (!user.getFineractClientId().equals(account.getClientId())) throw denied();
            String status = "blocked".equals(card.getStatus()) ? "blocked"
                    : card.getExpiresOn().isBefore(LocalDate.now(ZoneOffset.UTC)) ? "expired" : "active";
            long balance = new BigDecimal(account.getSummary().getAccountBalance().toString())
                    .movePointRight(2).longValueExact();
            return new CustomerCardData(card.getId(), card.getName(), card.getCardNumber(), card.getCurrency(),
                    status, card.getExpiresOn(), account.getId(), account.getAccountNo(),
                    card.getAccountExternalId(), balance);
        }).toList();
    }

    @Transactional
    public ConsentData begin(Jwt client, String number, String email) {
        policy.authorize(client, ConsumerAction.OPENBANKING_TPP_CONSENT_CREATE);
        if (!BankCard.validNumber(number) || email == null) throw invalidCard();
        BankCard card = cards.findByCardNumber(number).orElseThrow(BankCardService::invalidCard);
        if (!card.usable() || !card.getOwnerEmail().equalsIgnoreCase(email)) throw invalidCard();
        var user = users.findByEmail(card.getOwnerEmail()).orElseThrow(BankCardService::invalidCard);
        var account = account(card);
        if (user.getStatus() != org.apache.fineract.consumer.user.command.data.UserStatus.BOUND
                || !user.getFineractClientId().equals(account.getClientId())) throw invalidCard();
        OpenBankingConsent consent = OpenBankingConsent.createAwaitingAuthorisation(UUID.randomUUID(),
                client.getSubject(), Set.of(OpenBankingPermission.READ_ACCOUNTS_BASIC,
                        OpenBankingPermission.READ_BALANCES, OpenBankingPermission.INITIATE_PAYMENTS),
                properties.getConsentTtl());
        consent.bindCard(card.getId(), email.toLowerCase(java.util.Locale.ROOT));
        consents.saveAndFlush(consent);
        return new ConsentData(consent.getId(), card.getId(), card.getName(), card.maskedNumber(), card.getCurrency());
    }

    /** Called inside the actual bank authorization ceremony, including direct POSTs. */
    public void validateHolder(UUID consentId, UUID userId) {
        OpenBankingConsent consent = consents.findById(consentId)
                .orElseThrow(() -> new AccessDeniedException("Card authorization was not found"));
        if (consent.getBankCardId() == null) return;
        BankCard card = cards.findById(consent.getBankCardId()).orElseThrow(BankCardService::invalidCard);
        var user = users.findByPublicId(userId)
                .orElseThrow(() -> new AccessDeniedException("Card holder verification failed"));
        if (!card.usable() || user.getStatus() != org.apache.fineract.consumer.user.command.data.UserStatus.BOUND
                || !card.getOwnerEmail().equalsIgnoreCase(user.getEmail())
                || !card.getOwnerEmail().equalsIgnoreCase(consent.getWalletOwnerEmail())
                || !user.getFineractClientId().equals(account(card).getClientId())) {
            throw new AccessDeniedException("This card does not belong to the signed-in customer");
        }
    }

    public boolean allowsScopes(UUID consentId, Set<String> scopes) {
        var consent = consents.findById(consentId).orElseThrow(BankCardService::denied);
        if (consent.getBankCardId() == null) return !scopes.contains(READ_SCOPE);
        return scopes.contains(READ_SCOPE) && Set.of(READ_SCOPE, "openbanking:payments").containsAll(scopes);
    }

    public OpenBankingConsent consent(Jwt jwt, boolean allowRevoked) {
        UUID id;
        try { id = UUID.fromString(jwt.getClaimAsString(OAuth2Constants.CONSENT_ID)); }
        catch (IllegalArgumentException | NullPointerException error) { throw denied(); }
        OpenBankingConsent consent = consents.findById(id).orElseThrow(BankCardService::denied);
        boolean active = consent.getStatus() == ConsentStatus.AUTHORISED && consent.getExpiresAt().isAfter(Instant.now());
        if ((!active && !(allowRevoked && consent.getStatus() == ConsentStatus.REVOKED))
                || consent.getBankCardId() == null || consent.getUserId() == null
                || !jwt.getSubject().equals(consent.getUserId().toString())
                || !jwt.getAudience().contains(consent.getTppClientId())) throw denied();
        return consent;
    }

    public BankCard authorizedCard(Jwt jwt, OpenBankingConsent consent) {
        validateHolder(consent.getId(), UUID.fromString(jwt.getSubject()));
        return cards.findById(consent.getBankCardId()).orElseThrow(BankCardService::invalidCard);
    }

    public SavingsAccountData account(BankCard card) {
        var account = core.retrieveSavingsAccountByExternalId(card.getAccountExternalId());
        if (account.getStatus() == null || !Boolean.TRUE.equals(account.getStatus().getActive())
                || account.getCurrency() == null || !card.getCurrency().equals(account.getCurrency().getCode())) {
            throw invalidCard();
        }
        return account;
    }

    public CardData current(Jwt jwt) {
        if (!AccessPolicyEvaluator.hasScope(jwt, READ_SCOPE)) throw denied();
        var consent = consent(jwt, false);
        var card = authorizedCard(jwt, consent);
        var account = account(card);
        long balance = new BigDecimal(account.getSummary().getAccountBalance().toString())
                .movePointRight(2).longValueExact();
        return new CardData(card.getId(), card.getName(), card.maskedNumber(), card.getCurrency(), balance);
    }

    @Transactional
    public void revoke(Jwt jwt) {
        if (!AccessPolicyEvaluator.hasScope(jwt, READ_SCOPE)) throw denied();
        var consent = consent(jwt, true);
        if (consent.getStatus() != ConsentStatus.REVOKED) {
            consent.revoke();
            consents.saveAndFlush(consent);
        }
    }

    public CardData preview(UUID consentId, UUID userId) {
        validateHolder(consentId, userId);
        var consent = consents.findById(consentId).orElseThrow(BankCardService::denied);
        var card = cards.findById(consent.getBankCardId()).orElseThrow(BankCardService::invalidCard);
        return new CardData(card.getId(), card.getName(), card.maskedNumber(), card.getCurrency(), 0);
    }

    private static AccessDeniedException denied() { return new AccessDeniedException("Card authorization is not active"); }
    private static ResponseStatusException invalidCard() {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, "Card is invalid, unavailable or not owned by this user");
    }
}
