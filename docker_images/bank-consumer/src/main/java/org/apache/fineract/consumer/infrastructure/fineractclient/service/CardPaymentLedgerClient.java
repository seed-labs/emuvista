/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.infrastructure.fineractclient.service;

import java.util.Map;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/** Direct savings debit with a durable external reference and payee note. */
@FeignClient(name = "cardPaymentLedger", url = "${fineract.client.base-url}")
public interface CardPaymentLedgerClient {
    @GetMapping("/v1/paymenttypes")
    java.util.List<Map<String, Object>> paymentTypes();

    @PostMapping("/v1/savingsaccounts/{account}/transactions?command=withdrawal")
    Map<String, Object> debit(@PathVariable("account") Long account, @RequestBody Map<String, Object> request);

    @GetMapping("/v1/savingsaccounts/{account}/transactions/external-id/{externalId}")
    Map<String, Object> find(@PathVariable("account") Long account, @PathVariable("externalId") String externalId);
}
