/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

import { NgOptimizedImage } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import {
  IonButton,
  IonCard,
  IonCardContent,
  IonCardHeader,
  IonCardTitle,
} from '@ionic/angular/standalone';
import { TranslatePipe } from '../../core/adapters';

const SCOPE_LABEL_KEYS: Record<string, string> = {
  'openbanking:cards.read': 'View this card and its balance',
  'openbanking:accounts.read': 'consent.scope.accountsRead',
  'openbanking:payments': 'consent.scope.payments',
};

function csrfTokenFromCookie(): string {
  const match = document.cookie.match(/(?:^|;\s*)XSRF-TOKEN=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}

@Component({
  selector: 'app-consent',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgOptimizedImage,
    IonButton,
    IonCard,
    IonCardContent,
    IonCardHeader,
    IonCardTitle,
    TranslatePipe,
  ],
  template: `
    <ion-card class="page-card">
      <ion-card-header>
        <img
          ngSrc="/apache-fineract-logo.png"
          width="64"
          height="64"
          alt=""
          class="page-logo"
          priority
        />
        <ion-card-title>{{ 'consent.title' | appTranslate }}</ion-card-title>
      </ion-card-header>

      <ion-card-content>
        @if (valid) {
          <p>{{ 'consent.intro' | appTranslate: { tppClientId: tppClientId } }}</p>
          @if (card(); as selected) {
            <p><strong>{{ selected.name }} · {{ selected.maskedCard }} ({{ selected.currency }})</strong></p>
            <p>This authorization applies only to this card.</p>
          }
          @if (cardError()) {
            <p role="alert">This card cannot be authorized by the signed-in bank customer.</p>
          }
          <p>{{ 'consent.permissionsTitle' | appTranslate }}</p>
          <ul class="permissions">
            @for (scope of scopes; track scope) {
              <li>{{ scopeLabelKey(scope) | appTranslate }}</li>
            }
          </ul>
          <div class="actions">
            <form method="post" action="/api/v1/oauth2/authorize">
              <input type="hidden" name="client_id" [value]="tppClientId" />
              <input type="hidden" name="state" [value]="state" />
              <input type="hidden" name="_csrf" [value]="csrfToken" />
              <ion-button type="submit" fill="outline" color="medium">
                {{ 'consent.denyCta' | appTranslate }}
              </ion-button>
            </form>
            <form method="post" action="/api/v1/oauth2/authorize">
              <input type="hidden" name="client_id" [value]="tppClientId" />
              <input type="hidden" name="state" [value]="state" />
              <input type="hidden" name="_csrf" [value]="csrfToken" />
              @for (scope of scopes; track scope) {
                <input type="hidden" name="scope" [value]="scope" />
              }
              <ion-button type="submit" [disabled]="cardRequired && !card()">{{ 'consent.allowCta' | appTranslate }}</ion-button>
            </form>
          </div>
        } @else {
          <p>{{ 'consent.invalid' | appTranslate }}</p>
        }
      </ion-card-content>
    </ion-card>
  `,
  styleUrls: ['../../shared/css/centered-page.scss'],
  styles: `
    ion-card-header,
    ion-card-content {
      text-align: center;
    }

    .permissions {
      list-style-position: inside;
      padding-inline-start: 0;
    }

    .actions {
      display: flex;
      justify-content: center;
      gap: 0.5rem;
      margin-top: 1.5rem;
    }
  `,
})
export class ConsentComponent {
  private readonly route = inject(ActivatedRoute);

  protected readonly tppClientId = this.route.snapshot.queryParamMap.get('client_id') ?? '';
  protected readonly state = this.route.snapshot.queryParamMap.get('state') ?? '';
  protected readonly scopes = (this.route.snapshot.queryParamMap.get('scope') ?? '')
    .split(' ')
    .filter((scope) => scope.length > 0);
  protected readonly csrfToken = csrfTokenFromCookie();
  protected readonly valid = this.tppClientId !== '' && this.state !== '';

  protected readonly cardRequired = this.scopes.includes('openbanking:cards.read');
  protected readonly card = signal<{name: string; maskedCard: string; currency: string} | null>(null);
  protected readonly cardError = signal(false);

  constructor() {
    if (this.valid && this.cardRequired) {
      inject(HttpClient).get<{name: string; maskedCard: string; currency: string}>(
        '/api/v1/cards/authorization', {params: {state: this.state}},
      ).subscribe({next: card => this.card.set(card), error: () => this.cardError.set(true)});
    }
  }

  protected scopeLabelKey(scope: string): string {
    return SCOPE_LABEL_KEYS[scope] ?? scope;
  }
}
