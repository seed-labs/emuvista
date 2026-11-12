/* Licensed under the Apache License, Version 2.0. See LICENSE. */
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonInput } from '@ionic/angular/standalone';
import { RegistrationService } from '../registration/registration.service';
import { OtpComponent } from '../../shared/otp/otp.component';

@Component({
  selector: 'app-customer-registration',
  imports: [ReactiveFormsModule, RouterLink, IonButton, IonCard, IonCardContent, IonCardHeader, IonCardTitle, IonInput, OtpComponent],
  template: `
    <ion-card class="page-card">
      <ion-card-header><ion-card-title>Open a bank profile</ion-card-title></ion-card-header>
      <ion-card-content>
        @if (done()) {
          <p>Your email is verified. Log in, open Savings and choose Open account.</p>
          <ion-button routerLink="/login">Log in</ion-button>
        } @else if (registrationId()) {
          <app-otp [sentTo]="sentTo()" [loading]="loading()" (submitted)="verify($event)" (cancelled)="cancel()" />
          <ion-button fill="clear" [disabled]="loading()" (click)="sendCode()">Resend verification code</ion-button>
        } @else {
          <form [formGroup]="form" (ngSubmit)="register()">
            <ion-input formControlName="firstName" label="First name" labelPlacement="stacked" fill="outline" autocomplete="given-name" />
            <ion-input formControlName="lastName" label="Last name" labelPlacement="stacked" fill="outline" autocomplete="family-name" />
            <ion-input formControlName="email" type="email" label="Email" labelPlacement="stacked" fill="outline" autocomplete="email" />
            <ion-input formControlName="password" type="password" label="Password" labelPlacement="stacked" fill="outline" autocomplete="new-password"
              helperText="15–64 characters, including uppercase, lowercase, a number and a symbol." />
            <ion-button type="submit" [disabled]="loading() || form.invalid">Register</ion-button>
          </form>
          <p>Already have customer details from the bank? <a routerLink="/register-existing">Activate online banking</a>.</p>
        }
        @if (error()) { <p role="alert">{{ error() }}</p> }
        <p><a routerLink="/login">Back to login</a></p>
      </ion-card-content>
    </ion-card>
  `,
  styleUrls: ['../../shared/css/centered-page.scss', '../../shared/css/form.scss'],
})
export class CustomerRegistrationComponent {
  private readonly http = inject(HttpClient);
  private readonly native = inject(RegistrationService);
  private readonly fb = inject(NonNullableFormBuilder);
  protected readonly registrationId = signal('');
  protected readonly sentTo = signal<string | null>(null);
  protected readonly done = signal(false);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly form = this.fb.group({
    firstName: ['', [Validators.required, Validators.maxLength(50)]],
    lastName: ['', [Validators.required, Validators.maxLength(50)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(15), Validators.maxLength(64),
      Validators.pattern(/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).+$/)]],
  });
  protected register(): void {
    if (this.form.invalid) return;
    this.loading.set(true); this.error.set('');
    this.http.post<{registrationId: string}>('/api/v1/registration/open', this.form.getRawValue()).subscribe({
      next: data => { this.registrationId.set(data.registrationId); this.sendCode(); },
      error: error => this.fail(error),
    });
  }
  protected sendCode(): void {
    this.loading.set(true); this.error.set('');
    this.native.sendOtp({registrationId: this.registrationId(), deliveryMethod: 'email'}).subscribe({
      next: data => { this.sentTo.set(data.sentTo ?? null); this.loading.set(false); },
      error: error => this.fail(error),
    });
  }
  protected verify(token: string): void {
    this.loading.set(true); this.error.set('');
    this.native.verifyOtp({registrationId: this.registrationId(), token}).subscribe({
      next: () => { this.done.set(true); this.loading.set(false); },
      error: error => this.fail(error),
    });
  }
  protected cancel(): void { this.registrationId.set(''); this.error.set(''); }
  private fail(error: HttpErrorResponse): void {
    this.loading.set(false);
    this.error.set(error.status === 409 ? 'This email is already registered. Log in or reset your password.' :
      'Could not complete this step. Check your details and try again.');
  }
}
