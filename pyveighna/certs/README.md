# Broker TLS trust

Russian Trusted Root CA, fetched 2026-09-21 over verified HTTPS from:
https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer

T-Invest instructions: https://developer.tbank.ru/invest/intro/developer/network

SHA-256 (DER): D26D2D0231B7C39F92CC738512BA54103519E4405D68B5BD703E9788CA8ECF31
Validity: 2022-03-01 through 2032-02-27.

Used explicitly for broker gRPC channels only. The server supplies intermediate
certificates. Chain, expiration and hostname verification remain enabled.
No system trust store changes or global gRPC/environment overrides.
Update from the official source and update the fingerprint test when rotating.
