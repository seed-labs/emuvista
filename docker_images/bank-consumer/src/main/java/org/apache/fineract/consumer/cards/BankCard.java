/* Licensed under the Apache License, Version 2.0. See LICENSE. */
package org.apache.fineract.consumer.cards;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.util.UUID;
import lombok.Getter;
import lombok.NoArgsConstructor;

/** A simulated debit card; balances remain in the linked Fineract account. */
@Entity
@Table(name = "bank_cards")
@Getter
@NoArgsConstructor
public class BankCard {
    @Id private UUID id;
    @Column(nullable = false, unique = true, length = 19) private String cardNumber;
    @Column(nullable = false, length = 100) private String name;
    @Column(nullable = false, length = 50) private String accountExternalId;
    @Column(nullable = false, length = 254) private String ownerEmail;
    @Column(nullable = false, length = 3) private String currency;
    @Column(nullable = false, length = 16) private String status;
    @Column(nullable = false) private LocalDate expiresOn;

    public static BankCard create(UUID id, String number, String name, String account, String email,
            String currency, String status, LocalDate expires) {
        BankCard card = new BankCard();
        card.id = id; card.cardNumber = number; card.name = name; card.accountExternalId = account;
        card.ownerEmail = email; card.currency = currency; card.status = status; card.expiresOn = expires;
        return card;
    }

    public String maskedNumber() { return cardNumber.substring(cardNumber.length() - 4); }
    public boolean usable() { return "active".equals(status) && !expiresOn.isBefore(LocalDate.now()); }

    public static boolean validNumber(String number) {
        if (number == null || !number.matches("[0-9]{16,19}")) return false;
        int sum = 0; boolean twice = false;
        for (int i = number.length() - 1; i >= 0; i--) {
            int digit = number.charAt(i) - '0';
            if (twice) { digit *= 2; if (digit > 9) digit -= 9; }
            sum += digit; twice = !twice;
        }
        return sum % 10 == 0;
    }
}
