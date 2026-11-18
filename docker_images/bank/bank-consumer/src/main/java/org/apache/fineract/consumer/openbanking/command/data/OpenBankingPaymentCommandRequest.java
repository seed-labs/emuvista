/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.data;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;
import java.util.UUID;
import lombok.Builder;
import lombok.EqualsAndHashCode;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.ToString;

@Getter
@RequiredArgsConstructor
@Builder
@EqualsAndHashCode
@ToString(onlyExplicitlyIncluded = true)
public final class OpenBankingPaymentCommandRequest {
    @NotNull private final UUID cardId;
    @Positive private final Long fromAccountId;
    @NotNull @DecimalMin("0.01") @DecimalMax("1000000") @Digits(integer = 7, fraction = 2)
    private final BigDecimal amount;
    @NotBlank @Pattern(regexp = "[A-Z]{3}") private final String currency;
    @NotBlank @Size(max = 128) private final String payeeId;
    @NotBlank @Size(max = 255) private final String payeeName;
    @NotBlank @Size(max = 500) private final String description;
}
