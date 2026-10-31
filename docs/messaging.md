# Private buyer–seller messaging

The `messaging` application provides the first REST-only version of private
buyer–seller conversations. It deliberately contains no business WebSocket
consumer, presence tracking, push notification, reassignment, or group chat.

## Participants and seller eligibility

A conversation always belongs to one Business and contains exactly two
participants: its buyer and one seller selected by that buyer. The seller list
contains only active members of the requested active Business who:

- are not the authenticated buyer;
- have effective `MESSAGING_VIEW` and `MESSAGING_REPLY` permissions;
- have an active identity according to the local identity model.

Business owners receive the two permissions implicitly. Roles do not grant
messaging access. An owner, manager, or other seller still cannot read a
conversation unless that identity is its designated seller. A suspended,
removed, or no-longer-authorized seller loses access. Seller eligibility is
checked again when a conversation is created and before a message is sent.

## Persistence and states

`Conversation` stores an opaque public reference, Business, buyer, seller,
status, timestamps, and the last-message timestamp. Database constraints keep
the participants distinct and make `(business, buyer, seller)` unique.
Creation locks the selected membership and handles the uniqueness race.

`Message` stores an opaque public reference, explicit server-derived sender and
recipient, content, optional reply, optional Cart, optional private attachment
metadata, and `sent_at`, `received_at`, and `read_at`. Database and model
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
| `GET` | `/api/v1/messaging/conversations/{conversation}/` | Read one accessible conversation |
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

The schema is introduced by `messaging/migrations/0001_initial.py`. Generate and
review migrations locally, then apply them only through the authorized release
process. Tests cover eligibility, privacy between buyers and sellers, owner
isolation, revoked access, concurrency, replies, carts, attachment validation
and download authorization, deletion cleanup, state transitions, and receipt /
read invariants.
