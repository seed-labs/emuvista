/* Licensed under the Apache License, Version 2.0. See LICENSE. */
import { CurrencyPipe, DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle } from '@ionic/angular/standalone';

interface BankCard {
  cardId: string;
  name: string;
  number: string;
  currency: string;
  status: string;
  expiresOn: string;
  accountId: number;
  accountNumber: string;
  balanceMinor: number;
}

@Component({
  selector: 'app-bank-cards',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CurrencyPipe, DatePipe, RouterLink, IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle],
  template: `
    <ion-card>
      <ion-card-header><ion-card-title>Bank cards</ion-card-title></ion-card-header>
      <ion-card-content>
        @if (loading()) {
          <p>Loading cards…</p>
        } @else if (error()) {
          <p role="alert">Unable to load cards.</p>
        } @else {
          @for (card of visibleCards(); track card.cardId) {
            <article class="bank-card" [attr.data-card-number]="card.number">
              <div class="card-heading"><strong>{{ card.name }}</strong><span>{{ card.status }}</span></div>
              <p class="card-number"><span>Card number: </span><strong>{{ card.number }}</strong></p>
              <p><a [routerLink]="['/savings', card.accountId]">Account number: {{ card.accountNumber }}</a></p>
              <p>Balance: {{ card.balanceMinor / 100 | currency: card.currency }}</p>
              <p>Expires: {{ card.expiresOn | date: 'MM/yyyy' }}</p>
              <ion-button size="small" fill="outline" (click)="copy(card)">
                {{ copied() === card.cardId ? 'Copied' : 'Copy card number' }}
              </ion-button>
            </article>
          } @empty {
            <p>No cards issued for this account.</p>
          }
          @if (copyError()) { <p role="alert">Copy failed. Select the card number to copy it manually.</p> }
        }
      </ion-card-content>
    </ion-card>
  `,
  styles: `
    ion-card { margin: 0 0 1rem; }
    .bank-card + .bank-card { border-top: 1px solid var(--border); margin-top: 1rem; padding-top: 1rem; }
    .card-heading { display: flex; justify-content: space-between; gap: 1rem; }
    .card-heading span { text-transform: capitalize; }
    .card-number { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .card-number strong { user-select: all; }
  `,
})
export class BankCardsComponent {
  readonly accountId = input<number>();
  private readonly cards = signal<BankCard[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal(false);
  protected readonly copied = signal('');
  protected readonly copyError = signal(false);
  protected readonly visibleCards = computed(() => this.cards().filter(card =>
    this.accountId() === undefined || card.accountId === this.accountId()).sort((left, right) =>
      Number(right.status === 'active') - Number(left.status === 'active') || left.name.localeCompare(right.name)));

  constructor() {
    inject(HttpClient).get<BankCard[]>('/api/v1/cards').subscribe({
      next: cards => { this.cards.set(cards); this.loading.set(false); },
      error: () => { this.error.set(true); this.loading.set(false); },
    });
  }

  protected async copy(card: BankCard): Promise<void> {
    this.copyError.set(false);
    try {
      await navigator.clipboard.writeText(card.number);
      this.copied.set(card.cardId);
    } catch { this.copyError.set(true); }
  }
}
