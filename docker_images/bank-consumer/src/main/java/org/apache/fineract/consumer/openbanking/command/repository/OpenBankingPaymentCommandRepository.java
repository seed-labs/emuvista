/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.openbanking.command.repository;

import java.util.UUID;
import org.apache.fineract.consumer.openbanking.command.domain.OpenBankingPaymentCommandEntity;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OpenBankingPaymentCommandRepository extends JpaRepository<OpenBankingPaymentCommandEntity, UUID> {
}
