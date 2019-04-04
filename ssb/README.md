# Content of directory ssb/

dir   | content
---:  | ---
local | access to local files (log, indices)
rpc   | SSB RPC protocol
shs   | SSB secure handshake protocol

and their dependencies:

```txt
+-----------------------------+
|        your app here        |
+-----------+-----------------+
| rpc |     |     local       |
+-----+     +                 |
|    shs    |                 |
`-----------+-----------------'
```

---
