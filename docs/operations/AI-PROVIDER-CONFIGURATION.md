# AI Provider Configuration

## Where to configure

1. Sign in as `Organization Admin` or `SaaS Root`.
2. Open **Admin & Security → Администрирование → Настройки**.
3. Use the dedicated **AI Provider / OpenAI / Gemini** panel above the advanced flags table.

The `ai_copilot_enabled=true` row is only a feature flag. It does not select a provider and
does not configure an API key.

## OpenAI

1. Create an API key in [OpenAI Platform](https://platform.openai.com/api-keys).
2. Select **OpenAI** in the provider panel.
3. Paste the API key into **API key**.
4. Set the model available to the OpenAI project and keep the default base URL
   `https://api.openai.com/v1` unless an approved OpenAI-compatible gateway is used.
5. Keep **PII redaction** enabled.
6. Click **Проверить подключение**.
7. After a successful check, click **Сохранить и активировать**.

A ChatGPT subscription and an OpenAI API account are separate products. The platform requires
an API key; a ChatGPT login or password cannot be used here.

## Gemini

1. Create a restricted key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Select **Gemini**.
3. Paste the key and enter a model available to the Google project.
4. Keep **PII redaction** enabled.
5. Click **Проверить подключение**, then **Сохранить и активировать**.

Restrict the key to the Gemini / Generative Language API and to the backend environment where
possible. Never place provider keys in frontend source, browser local storage, screenshots, or
support tickets.

## Secret behaviour

- A newly entered key is sent only to the SBS AI ITSM backend.
- Read APIs return only `openai_api_key_configured` and `gemini_api_key_configured` booleans.
- Saved values are never returned to the browser; replacing a key requires entering a new one.
- Removing the active provider key automatically switches the platform to **Mock**.
- Changes are written to the tamper-evident administrative audit trail without key values.
- For production deployments, prefer environment-injected secrets or an external KMS/Vault and
  rotate keys according to the organization's security policy.

## Safe fallback

If a real provider is unavailable, classification falls back to the local deterministic Mock
provider. This keeps Service Desk workflows available, but the provider status should be
monitored because Mock results are rules-based rather than LLM-generated.

## Troubleshooting

- **API key missing**: enter a new key or verify that the corresponding environment variable is
  available to the backend.
- **HTTP 401/403**: the key is invalid, revoked, restricted incorrectly, or lacks project access.
- **HTTP 404**: the selected model is unavailable to the provider project.
- **HTTP 429**: quota or rate limit has been reached.
- **Transport error**: check outbound HTTPS, proxy, DNS, certificates, and the configured timeout.
- Do not paste a real key into chat or logs. Use the password field in the admin panel.
