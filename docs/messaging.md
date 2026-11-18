# Customer–business commercial messaging

The `messaging` application provides private buyer–business conversations over
REST and Django Channels. Conversations belong to the Business rather than to
an individual employee. Each Business has one effective messaging agent.

When no employee is designated, the active `OWNER` is the effective agent. A
designation is accepted only for an active member with `MESSAGING_VIEW` and
`MESSAGING_REPLY`. The owner replaces or clears it transactionally. If the
member is suspended, removed, deactivated, or loses either permission, the
effective agent falls back to the owner. The backend recomputes this rule on
every send; a stale browser cannot send as a former agent.

`BusinessMessagingSettings` stores this configuration. `Inquiry` stores a
structured commercial request and snapshots the product reference and name so
the original request remains readable after a product is edited or archived.

## Participants and seller eligibility

A conversation always belongs to one Business and contains a buyer plus the
company side. Legacy rows retain their original seller identity for history;
new writes route to the effective agent. The compatibility seller endpoint now
returns only the effective agent and is not a selection mechanism. The company
side contains only active members who:

- are not the authenticated buyer;
- have effective `MESSAGING_VIEW` and `MESSAGING_REPLY` permissions;
- have an active identity according to the local identity model.

An identity with an `ACTIVE` `BusinessMember` record for the requested Business
cannot act as a buyer for that Business. This is enforced by the service layer
with the stable error code `BUSINESS_MEMBER_CANNOT_CONTACT_SELLER`. Suspended
and removed memberships follow the existing cart rule and do not block this
buyer role. Existing history remains readable according to the normal
conversation access rules, but new buyer messages and WebSocket tickets are
rejected.

Business owners receive the two permissions implicitly. Members with
`MESSAGING_VIEW` can read the shared Business inbox, but only the effective
agent can reply. The owner cannot reply while an eligible employee is
designated. Agent eligibility is checked again before every message.

## Persistence and states

`Conversation` stores an opaque public reference, Business, buyer, the
historical initial seller, a direct/inquiry kind, status, timestamps, and the
last-message timestamp. Existing participant constraints remain in place.
Creation locks the Business settings and handles the uniqueness race.

`Message` stores an opaque public reference, explicit server-derived sender and
recipient, an optional immutable `sender_member` audit link for company replies,
content, optional reply, optional Cart, optional private attachment metadata,
and `sent_at`, `received_at`, and `read_at`. Database and model
constraints require different participants, a text or attachment, and prevent
receipt/read timestamps before transmission.

Conversation states are:

- `OPEN`: messages are accepted;
- `CLOSED`: history remains available, but messages are rejected until reopen;
- `ARCHIVED`: history remains available and the conversation cannot be reopened
  through this API.

No archive endpoint is exposed in this version.

## REST endpoints

All routes require the normal Ecommerce JWT authentication, including the
seller-selection route despite its placement under `public/`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/public/businesses/{business}/messaging-sellers/` | List the minimal eligible-seller projection |
| `GET`, `POST` | `/api/v1/messaging/conversations/` | List accessible conversations or create/find one |
| `GET`, `POST` | `/api/v1/messaging/inquiries/` | List or create a structured commercial request |
| `GET`, `PATCH` | `/api/v1/messaging/inquiries/{inquiry}/` | Read or update an inquiry workflow status |
| `GET` | `/api/v1/messaging/businesses/{business}/settings/` | Read messaging settings and effective agent |
| `PATCH` | `/api/v1/messaging/businesses/{business}/settings/` | Owner-only designation, reset, or enable/disable |
| `GET` | `/api/v1/messaging/conversations/{conversation}/` | Read one accessible conversation |
| `POST` | `/api/v1/messaging/conversations/{conversation}/websocket-ticket/` | Issue a short-lived, one-use WebSocket ticket |
| `POST` | `/api/v1/messaging/conversations/{conversation}/close/` | Close a conversation |
| `POST` | `/api/v1/messaging/conversations/{conversation}/reopen/` | Reopen a closed conversation |
| `GET`, `POST` | `/api/v1/messaging/conversations/{conversation}/messages/` | Paginate history or send a message |
| `GET` | `/api/v1/messaging/conversations/{conversation}/messages/{message}/` | Read one message |
| `POST` | `/api/v1/messaging/conversations/{conversation}/messages/{message}/received/` | Recipient confirms receipt |
| `POST` | `/api/v1/messaging/conversations/{conversation}/messages/{message}/read/` | Recipient confirms reading |
| `GET` | `/api/v1/messaging/conversations/{conversation}/messages/{message}/attachment/` | Authorized private download |

Conversation and message histories use page-number pagination (50 by default,
100 maximum). Optional conversation filters are `business` and `status`.

The server ignores client attempts to provide a sender or recipient. A reply
must cite a message from the same conversation. A Cart is projected only as
reference, name, and status, and must belong to both the conversation buyer and
Business. Receipt and reading confirmations are idempotent and can only be made
by the message recipient; reading does not require a prior receipt event.

## Private attachments

Attachments use `MESSAGING_PRIVATE_MEDIA_ROOT`, which must not be mapped to a
public web root. Files receive opaque storage paths and are downloaded only
through the authenticated view with `private, no-store`, `nosniff`, and sandbox
headers. There is no permanent public URL.

Accepted formats are JPEG, PNG, WebP, and PDF. The backend ignores the MIME type
claimed by the client, validates image bytes with Pillow, checks the PDF header
and end marker, normalizes the extension and name, enforces the configured size
limit, and records a SHA-256 digest. A file is removed after the database
deletion of its Message commits.

Configuration:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MESSAGING_PRIVATE_MEDIA_ROOT` | `backend/private_media/messaging` | Non-public local storage root |
| `MESSAGING_ATTACHMENT_MAX_BYTES` | `8388608` | Maximum attachment size (8 MiB) |
| `MESSAGING_MESSAGE_MAX_LENGTH` | `4000` | Maximum text length |

For multi-instance production, replace or mount this path with protected shared
storage (or a private object-store backend) and add malware scanning according
to the deployment policy. The current validation is format validation, not an
antivirus engine.

## Migration and tests

The transition is introduced by `messaging/migrations/0003_business_messaging_center.py`.
It preserves existing columns and rows, adds the agent audit link, settings,
inquiries, and conversation kind, and backfills only sender memberships that
can be matched exactly. Review and apply it only through the authorized release
process; this task does not apply migrations in production.

## WebSocket

The browser obtains a ticket from the REST endpoint and opens:
`/ws/messaging/conversations/{conversation}/` with the subprotocol
`carri-messaging-v1` and the opaque ticket as its second protocol value. The
ticket is stored hashed, expires after 45 seconds and is consumed atomically.
The consumer joins only the conversation group and rechecks participant and
seller permissions before accepting the connection and each write.
