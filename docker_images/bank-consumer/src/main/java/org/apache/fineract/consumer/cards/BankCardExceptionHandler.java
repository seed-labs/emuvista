/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import org.apache.fineract.consumer.infrastructure.exception.ConsumerApiError;
import org.apache.fineract.consumer.openbanking.command.api.OpenBankingPaymentCommandController;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

@Order(Ordered.HIGHEST_PRECEDENCE)
@RestControllerAdvice(assignableTypes = { BankCardController.class, BankCardAuthorizationController.class, BankCustomerCardController.class,
        OpenBankingPaymentCommandController.class })
public class BankCardExceptionHandler {
    @ExceptionHandler(AccessDeniedException.class)
    public ResponseEntity<ConsumerApiError> denied(AccessDeniedException error) {
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(ConsumerApiError.builder()
                .code("bank.card.authorization.denied")
                .defaultMessage("Card authorization or ownership verification failed").build());
    }

    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ConsumerApiError> invalid(ResponseStatusException error) {
        return ResponseEntity.status(error.getStatusCode()).body(ConsumerApiError.builder()
                .code("bank.card.invalid").defaultMessage("Card is invalid, unavailable or not owned by this user").build());
    }
}
