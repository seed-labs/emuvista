/* Licensed under the Apache License, Version 2.0. See LICENSE. */
import { HttpClient } from '@angular/common/http';
import { Component, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonSelect, IonSelectOption } from '@ionic/angular/standalone';

interface Product { id: number; name: string; currency: {code: string}; }
@Component({
  selector: 'app-open-account',
  imports: [FormsModule, IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonSelect, IonSelectOption],
  template: `
    <ion-card>
      <ion-card-header><ion-card-title>Open account</ion-card-title></ion-card-header>
      <ion-card-content>
        <ion-select [(ngModel)]="productId" label="Account product" interface="popover">
          @for (product of products(); track product.id) {
            <ion-select-option [value]="product.id">{{ product.name }} ({{ product.currency.code }})</ion-select-option>
          }
        </ion-select>
        <p>New accounts start with a zero balance. Deposits are recorded by bank staff.</p>
        <ion-button [disabled]="busy() || !productId" (click)="open()">Open account</ion-button>
        @if (message()) { <p role="status">{{ message() }}</p> }
      </ion-card-content>
    </ion-card>
  `,
})
export class OpenAccountComponent {
  private readonly http = inject(HttpClient);
  private requestId = crypto.randomUUID();
  private requestedProduct?: number;
  readonly opened = output<void>();
  protected readonly products = signal<Product[]>([]);
  protected readonly busy = signal(false);
  protected readonly message = signal('');
  protected productId?: number;
  constructor() {
    this.http.get<Product[]>('/api/v1/customer-accounts/products').subscribe({
      next: data => { this.products.set(data); this.productId = data[0]?.id; },
      error: () => this.message.set('Unable to load account products. Reload to try again.'),
    });
  }
  protected open(): void {
    if (this.requestedProduct !== undefined && this.requestedProduct !== this.productId) {
      this.message.set('Retry the original account product until its application is resolved.'); return;
    }
    this.requestedProduct = this.productId;
    this.busy.set(true); this.message.set('');
    this.http.post('/api/v1/customer-accounts', {productId: this.productId, id: this.requestId}).subscribe({
      next: () => {
        this.busy.set(false); this.message.set('Account opened with a zero balance.');
        this.requestId = crypto.randomUUID(); this.requestedProduct = undefined; this.opened.emit();
      },
      error: () => { this.busy.set(false); this.message.set('Could not confirm account opening. Retry to check the same application.'); },
    });
  }
}
