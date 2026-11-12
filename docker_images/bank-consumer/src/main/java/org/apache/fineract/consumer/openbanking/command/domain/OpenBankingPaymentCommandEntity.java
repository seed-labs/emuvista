/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.util.UUID;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** A committed request fences uncertain remote writes against another debit. */
@Entity
@Table(name = "open_banking_payments")
@Getter
@NoArgsConstructor
public class OpenBankingPaymentCommandEntity {
    @Id private UUID id;
    @Column(nullable = false) private UUID consentId;
    @Column(nullable = false, length = 100) private String tppClientId;
    @Column(nullable = false) private Long fromAccountId;
    private UUID bankCardId;
    @Column(nullable = false, precision = 19, scale = 2) private BigDecimal amount;
    @Column(nullable = false, length = 3) private String currency;
    @Column(nullable = false, length = 31) private String status;
    private Long transactionId;
    private String platform;
    private String payeeId;
    private String payeeName;
    @Column(length = 500) private String description;
    private java.time.Instant createdAt;

    public static OpenBankingPaymentCommandEntity requested(UUID id, UUID consentId, String tppClientId,
            Long fromAccountId, UUID bankCardId, BigDecimal amount, String currency,
            String platform, String payeeId, String payeeName, String description) {
        OpenBankingPaymentCommandEntity payment = new OpenBankingPaymentCommandEntity();
        payment.id = id;
        payment.consentId = consentId;
        payment.tppClientId = tppClientId;
        payment.fromAccountId = fromAccountId;
        payment.bankCardId = bankCardId;
        payment.amount = amount;
        payment.currency = currency;
        payment.platform = platform;
        payment.payeeId = payeeId;
        payment.payeeName = payeeName;
        payment.description = description;
        payment.createdAt = java.time.Instant.now();
        payment.status = "pending";
        return payment;
    }

    public void complete(Long transactionId) {
        this.transactionId = transactionId;
        status = "completed";
    }

    public void requireReview() {
        status = "needs_review";
    }

    public void decline() {
        status = "declined";
    }
}
