# Fabric Genuine.js 1.0.1

This repo will help you create your repos, deploy them directly onto your
staging and production servers and keep them updated as you want.

This project uses Fabric which is a python library.

All the requirements are into the requirements.txt

### ENV variables

To keep the 12 factor ideas, this tool needs env variables

- **VAULT_URL**

### Vault

You need to create a Vault with these two jsons in the route below

**secret/passwords**
```json
{
  "passwords" : {
    "bitbucket" : {
      "username" : "Your username",
      "password" : "Your password",
      "team" : "Your team name"
    }
  }
}
```

**secret/servers**
```json
{
  "servers" : {
    "staging" : {
      "ip" : "127.0.0.1",
      "dns" : "example.com"
    },
    "production" : {
      "ip" : "127.0.0.1",
      "dns" : "example.com"
    }
  }
}
```
