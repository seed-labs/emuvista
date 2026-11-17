/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.service;

import feign.FeignException;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.access.data.ConsumerAction;
import org.apache.fineract.consumer.infrastructure.access.service.AccessPolicyEvaluator;
import java.util.Map;
import org.apache.fineract.consumer.infrastructure.fineractclient.service.CardPaymentLedgerClient;
import org.apache.fineract.consumer.infrastructure.idempotency.service.IdempotencyKeyHolder;
import org.apache.fineract.consumer.infrastructure.idempotency.service.IdempotencyKeyDeriver;
import org.apache.fineract.consumer.infrastructure.oauth2.data.OAuth2Constants;
import org.apache.fineract.consumer.infrastructure.oauth2.service.PaymentClientConfiguration;
import org.apache.fineract.consumer.openbanking.command.data.ConsentStatus;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandData;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandRequest;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPermission;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingConsent;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingPaymentCommandEntity;
import org.apache.fineract.consumer.openbanking.command.exception.OpenBankingPaymentInvalidException;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingConsentCommandRepository;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingPaymentCommandRepository;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class OpenBankingPaymentCommandServiceImpl implements OpenBankingPaymentCommandService {
    private final OpenBankingConsentCommandRepository consentRepository;
    private final OpenBankingPaymentCommandRepository paymentRepository;
    private final AccessPolicyEvaluator policy;
    private final CardPaymentLedgerClient ledger;
    private final IdempotencyKeyHolder idempotencyKeyHolder;
    private final org.apache.fineract.consumer.cards.BankCardService cards;

    private final PaymentClientConfiguration paymentClients;

    @Override
    public OpenBankingPaymentCommandData debit(Jwt jwt, UUID requestId, OpenBankingPaymentCommandRequest request) {
        OpenBankingConsent consent = requireConsent(jwt);
        var card = cards.authorizedCard(jwt, consent);
        var source = cards.account(card);
        if (!card.getId().equals(request.getCardId())
                || request.getFromAccountId() != null && !source.getId().equals(request.getFromAccountId())) {
            throw new OpenBankingPaymentInvalidException();
        }
        policy.authorize(jwt, ConsumerAction.OPENBANKING_PAYMENT_EXECUTE, source.getId(),
                OpenBankingPaymentInvalidException::new);
        var partner = paymentClients.find(consent.getTppClientId());
        if (partner == null) {
            throw new OpenBankingPaymentInvalidException();
        }
        if (source.getCurrency() == null || !request.getCurrency().equals(source.getCurrency().getCode())) {
            throw new OpenBankingPaymentInvalidException();
        }
        var existing = paymentRepository.findById(requestId);
        if (existing.isPresent()) {
            return replay(existing.get(), consent, request);
        }
        var payment = OpenBankingPaymentCommandEntity.requested(requestId, consent.getId(),
                consent.getTppClientId(), source.getId(), card.getId(), request.getAmount(), request.getCurrency(),
                partner.platform(), request.getPayeeId(), request.getPayeeName(), request.getDescription());
        // The repository commits before the remote call. A competing or uncertain
        // request reads this record and cannot execute another debit.
        try {
            paymentRepository.saveAndFlush(payment);
        } catch (DataIntegrityViolationException exception) {
            return replay(paymentRepository.findById(requestId).orElseThrow(), consent, request);
        }
        idempotencyKeyHolder.set(IdempotencyKeyDeriver.derive(UUID.fromString(jwt.getSubject()), requestId.toString()));
        try {
            String note = "Card payment via " + partner.platform() + " to " + request.getPayeeName()
                    + " [" + request.getPayeeId() + "]; " + request.getDescription() + "; payment " + requestId;
            var paymentType = ledger.paymentTypes().stream().filter(type -> "Simulation".equals(type.get("name")))
                    .findFirst().orElseThrow(OpenBankingPaymentInvalidException::new).get("id");
            var result = ledger.debit(source.getId(), Map.of(
                    "transactionDate", LocalDate.now(java.time.ZoneOffset.UTC).toString(),
                    "transactionAmount", request.getAmount(), "locale", "en", "dateFormat", "yyyy-MM-dd",
                    "externalId", requestId.toString(), "note", note, "paymentTypeId", paymentType));
            Object transactionId = result.get("resourceId");
            if (transactionId instanceof Number number) payment.complete(number.longValue());
            else payment.requireReview();
        } catch (FeignException exception) {
            if (exception.status() == 400 || exception.status() == 403) {
                payment.decline();
            } else {
                payment.requireReview();
            }
        } catch (RuntimeException exception) {
            payment.requireReview();
        } finally {
            idempotencyKeyHolder.clear();
        }
        paymentRepository.saveAndFlush(payment);
        return acknowledgement(payment);
    }

    private OpenBankingConsent requireConsent(Jwt jwt) {
        OpenBankingConsent consent;
        try {
            consent = consentRepository.findById(UUID.fromString(jwt.getClaimAsString(OAuth2Constants.CONSENT_ID)))
                    .orElseThrow(() -> new AccessDeniedException("Payment consent is required"));
        } catch (IllegalArgumentException | NullPointerException exception) {
            throw new AccessDeniedException("Payment consent is required");
        }
        if (consent.getStatus() != ConsentStatus.AUTHORISED || !consent.getExpiresAt().isAfter(Instant.now())
                || !UUID.fromString(jwt.getSubject()).equals(consent.getUserId())
                || !jwt.getAudience().contains(consent.getTppClientId())
                || consent.getBankCardId() == null
                || !consent.getPermissions().contains(OpenBankingPermission.INITIATE_PAYMENTS)) {
            throw new AccessDeniedException("Payment consent is not active");
        }
        return consent;
    }

    private OpenBankingPaymentCommandData replay(OpenBankingPaymentCommandEntity payment,
            OpenBankingConsent consent, OpenBankingPaymentCommandRequest request) {
        if (!payment.getConsentId().equals(consent.getId())
                || !payment.getTppClientId().equals(consent.getTppClientId())
                || !java.util.Objects.equals(payment.getBankCardId(), request.getCardId())
                || request.getFromAccountId() != null && !payment.getFromAccountId().equals(request.getFromAccountId())
                || payment.getAmount().compareTo(request.getAmount()) != 0
                || !payment.getCurrency().equals(request.getCurrency())
                || !java.util.Objects.equals(payment.getPayeeId(), request.getPayeeId())
                || !java.util.Objects.equals(payment.getPayeeName(), request.getPayeeName())
                || !java.util.Objects.equals(payment.getDescription(), request.getDescription())) {
            throw new OpenBankingPaymentInvalidException();
        }
        return reconcile(payment);
    }

    public OpenBankingPaymentCommandData status(Jwt jwt, UUID id) {
        var payment = paymentRepository.findById(id).orElseThrow(OpenBankingPaymentInvalidException::new);
        // Revoking a card stops future debits, not historical receipt queries by
        // the authenticated payment platform which submitted that transaction.
        if (payment.getTppClientId().equals(jwt.getSubject())
                && AccessPolicyEvaluator.hasScope(jwt, "openbanking:payments")) return reconcile(payment);
        var consent = requireConsent(jwt);
        if (!payment.getTppClientId().equals(consent.getTppClientId())
                || !payment.getConsentId().equals(consent.getId())) throw new AccessDeniedException("Payment belongs to another consent");
        return reconcile(payment);
    }

    private OpenBankingPaymentCommandData reconcile(OpenBankingPaymentCommandEntity payment) {
        if (!"completed".equals(payment.getStatus()) && !"declined".equals(payment.getStatus())) {
            try {
                var row = ledger.find(payment.getFromAccountId(), payment.getId().toString());
                if (row.get("id") instanceof Number id) {
                    payment.complete(id.longValue());
                    paymentRepository.saveAndFlush(payment);
                }
            } catch (FeignException ignored) { /* Uncertain debits are never repeated. */ }
        }
        return acknowledgement(payment);
    }

    public static OpenBankingPaymentCommandData acknowledgement(OpenBankingPaymentCommandEntity payment) {
        return OpenBankingPaymentCommandData.builder().id(payment.getId()).status(payment.getStatus())
                .transactionId(payment.getTransactionId()).clientId(payment.getTppClientId())
                .platform(payment.getPlatform()).payeeId(payment.getPayeeId()).payeeName(payment.getPayeeName())
                .description(payment.getDescription()).amount(payment.getAmount()).currency(payment.getCurrency())
                .accountId(payment.getFromAccountId()).created(payment.getCreatedAt()).build();
    }
}
