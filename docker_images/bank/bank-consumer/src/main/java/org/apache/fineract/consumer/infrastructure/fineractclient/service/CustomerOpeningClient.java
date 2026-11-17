/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.infrastructure.fineractclient.service;

import java.util.List;
import java.util.Map;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

/** Native core operations; credentials remain in the bank backend. */
@FeignClient(name = "customerOpening", url = "${fineract.client.base-url}")
public interface CustomerOpeningClient {
    @GetMapping("/v1/clients/external-id/{externalId}")
    Map<String, Object> client(@PathVariable("externalId") String externalId);
    @PostMapping("/v1/clients")
    Map<String, Object> createClient(@RequestBody Map<String, Object> request);
    @GetMapping("/v1/savingsproducts")
    List<Map<String, Object>> products();
    @GetMapping("/v1/savingsaccounts/external-id/{externalId}")
    Map<String, Object> accountByReference(@PathVariable("externalId") String externalId);
    @GetMapping("/v1/savingsaccounts/{id}")
    Map<String, Object> account(@PathVariable("id") Long id);
    @PostMapping("/v1/savingsaccounts")
    Map<String, Object> createAccount(@RequestBody Map<String, Object> request);
    @PostMapping("/v1/savingsaccounts/{id}")
    Map<String, Object> accountCommand(@PathVariable("id") Long id, @RequestParam("command") String command,
            @RequestBody Map<String, Object> request);
    @PutMapping("/v1/savingsaccounts/{id}")
    Map<String, Object> updateAccount(@PathVariable("id") Long id, @RequestBody Map<String, Object> request);
}
