# Spec coverage map - RFC  MQTT 3.1.1 MUST clauses vs. what we test

Round-2 CTO gap: violation coverage was asserted, not measured. This map
is the measurement. "Tested" means an env action + response classifier
verdict exercises the clause against the live broker, with the compliant
behaviors pinned by tests/test_env_broker.py.

## Hunted violation classes (flag as CANDIDATES, replay-verified before counting)

| Class | Spec clause | Requirement | Env verdict | amqtt source evidence |
|---|---|---|---|---|
| V1 | [MQTT-3.1.2-2] / [MQTT-3.1.0-2] | Malformed CONNECT (bad protocol level) MUST get CONNACK rc=0x01 then connection close | silence + open socket after 1.5s confirm read | compliant path: `mqtt/protocol/broker_handler.py:200-227` (CONNACK rc=0x01 + close). CONFIRMED deviation in fuzzed contexts: non-CONNECT first packet wedges `init_from_connect`'s `ConnectPacket.from_stream` parse (`broker.py:489`, `broker_handler.py:157-167`) so the malformed CONNECT never gets its CONNACK. Replay regression: tests/test_replay_regression.py |
| V2 | [MQTT-3.1.0-2] | Second CONNECT on an established session MUST close the connection | CONNACK_OK or silence+open after confirm read | compliant path: `broker_handler.py:101-109`; pinned compliant by test_second_connect_after_valid_closes_no_v2 |
| V3 | [MQTT-3.1.0-1] | Server MUST NOT process packets before CONNECT succeeds | SUBACK observed with no prior successful CONNECT on the socket | CONNECT dispatch gate: `mqtt/protocol/handler.py:526` |
| V4 | [MQTT-3.1.2-2] | Malformed CONNECT MUST NOT receive CONNACK success | CONNACK rc=0x00 after malformed CONNECT | same rc=0x01 path as V1 (`broker_handler.py:200-227`) |
| CRASH | n/a (robustness) | broker process dies / port stops accepting under fuzz traffic | process poll + retried port probe | teardown: `broker.py:609/673` (wait_disconnect) |

## Compliant behaviors pinned by integration tests (must NOT flag)

| Behavior | Clause | Test |
|---|---|---|
| Single malformed CONNECT -> CONNACK rc=0x01 + close | [MQTT-3.1.2-2] | test_canonical_malformed_connect_is_compliant |
| Valid CONNECT -> CONNACK rc=0x00 | [MQTT-3.1.2-1] | test_valid_connect_gets_connack_ok |
| Second CONNECT after valid -> connection closed | [MQTT-3.1.0-2] | test_second_connect_after_valid_closes_no_v2 |
| Broker death -> crash oracle fires | robustness | test_crash_oracle_fires_on_broker_death |

## Degradation oracle (not a spec clause - the DoS class process death misses)

Per-episode side-channel probe: CONNECT->CONNACK RTT + broker fd count.
degraded_events fire when RTT > 2s or the probe fails while the process
lives. Motivation: observed live amqtt at 375+ CLOSE-WAIT fds, CPU pinned,
still "alive".

## Known coverage gaps (honest list)

- QoS 1/2 flows (PUBACK/PUBREC/PUBREL/PUBCOMP state machines) - action
  space sends QoS 0 only.
- Will messages, retained messages, session persistence across reconnect
  (clean_session=0 paths).
- WebSocket listener untested (env drives raw TCP only).
- Malformed remaining-length encodings and partial-packet (fragmentation)
  attacks - packets are always sent whole.
- Auth/ACL clauses: broker runs allow-anonymous, so auth-failure clauses
  are out of scope by configuration.
