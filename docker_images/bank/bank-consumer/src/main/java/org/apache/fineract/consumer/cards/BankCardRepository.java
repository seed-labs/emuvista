/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BankCardRepository extends JpaRepository<BankCard, UUID> {
    Optional<BankCard> findByCardNumber(String number);
    List<BankCard> findByOwnerEmailIgnoreCaseOrderByNameAsc(String email);
}
