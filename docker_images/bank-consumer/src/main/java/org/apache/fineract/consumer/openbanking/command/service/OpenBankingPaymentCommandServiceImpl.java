/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.service;

import feign.FeignException;
import java.time.Instant;
import java.time.LocalDate;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.consumer.infrastructure.access.data.ConsumerAction;
import org.apache.fineract.consumer.infrastructure.access.service.AccessPolicyEvaluator;
import org.apache.fineract.consumer.infrastructure.fineractclient.generated.model.AccountTransferRequest;
import org.apache.fineract.consumer.infrastructure.fineractclient.service.TransferFineractClient;
import org.apache.fineract.consumer.infrastructure.idempotency.service.IdempotencyKeyHolder;
import org.apache.fineract.consumer.infrastructure.idempotency.service.IdempotencyKeyDeriver;
import org.apache.fineract.consumer.infrastructure.oauth2.data.OAuth2Constants;
import org.apache.fineract.consumer.openbanking.command.data.ConsentStatus;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandData;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPaymentCommandRequest;
import org.apache.fineract.consumer.openbanking.command.data.OpenBankingPermission;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingConsent;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingPaymentCommandEntity;
import org.apache.fineract.consumer.openbanking.command.exception.OpenBankingPaymentInvalidException;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingConsentCommandRepository;
import org.apache.fineract.consumer.openbanking.command.repository.OpenBankingPaymentCommandRepository;
import org.springframework.beans.factory.annotation.Value;
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
    private final TransferFineractClient core;
    private final IdempotencyKeyHolder idempotencyKeyHolder;
    private final org.apache.fineract.consumer.cards.BankCardService cards;

    @Value("${consumer.payments.settlement-account:}")
    private String settlementExternalId;

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
        if (settlementExternalId.isBlank()) {
            throw new OpenBankingPaymentInvalidException();
        }
        var target = core.retrieveSavingsAccountByExternalId(settlementExternalId);
        if (source.getCurrency() == null || target.getCurrency() == null
                || !request.getCurrency().equals(source.getCurrency().getCode())
                || !request.getCurrency().equals(target.getCurrency().getCode())
                || source.getId().equals(target.getId())) {
            throw new OpenBankingPaymentInvalidException();
        }
        var existing = paymentRepository.findById(requestId);
        if (existing.isPresent()) {
            return replay(existing.get(), consent, request);
        }
        var payment = OpenBankingPaymentCommandEntity.requested(requestId, consent.getId(),
                consent.getTppClientId(), source.getId(), card.getId(), request.getAmount(), request.getCurrency());
        // The repository commits before the remote call. A competing or uncertain
        // request reads this record and cannot execute another debit.
        try {
            paymentRepository.saveAndFlush(payment);
        } catch (DataIntegrityViolationException exception) {
            return replay(paymentRepository.findById(requestId).orElseThrow(), consent, request);
        }
        idempotencyKeyHolder.set(IdempotencyKeyDeriver.derive(UUID.fromString(jwt.getSubject()), requestId.toString()));
        try {
            Long fromOffice = core.getClientOfficeId(source.getClientId());
            Long toOffice = core.getClientOfficeId(target.getClientId());
            var transfer = new AccountTransferRequest()
                    .fromOfficeId(String.valueOf(fromOffice)).fromClientId(String.valueOf(source.getClientId()))
                    .fromAccountId(String.valueOf(source.getId())).fromAccountType("2")
                    .toOfficeId(String.valueOf(toOffice)).toClientId(String.valueOf(target.getClientId()))
                    .toAccountId(String.valueOf(target.getId())).toAccountType("2")
                    .transferAmount(request.getAmount().toPlainString()).transferDate(LocalDate.now().toString())
                    .dateFormat("yyyy-MM-dd").locale("en").transferDescription("Wallet funding " + requestId);
            Long transferId = core.createAccountTransfer(transfer);
            if (transferId == null) {
                payment.requireReview();
            } else {
                payment.complete(transferId);
            }
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

    private static OpenBankingPaymentCommandData replay(OpenBankingPaymentCommandEntity payment,
            OpenBankingConsent consent, OpenBankingPaymentCommandRequest request) {
        if (!payment.getConsentId().equals(consent.getId())
                || !payment.getTppClientId().equals(consent.getTppClientId())
                || !java.util.Objects.equals(payment.getBankCardId(), request.getCardId())
                || request.getFromAccountId() != null && !payment.getFromAccountId().equals(request.getFromAccountId())
                || payment.getAmount().compareTo(request.getAmount()) != 0
                || !payment.getCurrency().equals(request.getCurrency())) {
            throw new OpenBankingPaymentInvalidException();
        }
        return acknowledgement(payment);
    }

    private static OpenBankingPaymentCommandData acknowledgement(OpenBankingPaymentCommandEntity payment) {
        return OpenBankingPaymentCommandData.builder().id(payment.getId()).status(payment.getStatus())
                .transferId(payment.getTransferId()).build();
    }
}
