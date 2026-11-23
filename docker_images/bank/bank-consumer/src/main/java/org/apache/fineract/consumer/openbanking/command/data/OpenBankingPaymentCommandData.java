/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.data;

import java.util.UUID;
import java.math.BigDecimal;
import lombok.Builder;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.ToString;

@Getter
@RequiredArgsConstructor
@Builder
@EqualsAndHashCode
@ToString
public final class OpenBankingPaymentCommandData {
    private final UUID id;
    private final String status;
    private final Long transactionId;
    private final String clientId;
    private final String platform;
    private final String payeeId;
    private final String payeeName;
    private final String description;
    private final BigDecimal amount;
    private final String currency;
    private final Long accountId;
    private final java.time.Instant created;
}
