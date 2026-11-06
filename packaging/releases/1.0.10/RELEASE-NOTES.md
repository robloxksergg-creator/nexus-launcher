# NEXUS 1.0.10 beta — review candidate

- Bounded, verified updater recovery and strict managed package/version checks.
- Pack-file resume validates complete byte ranges; broken network transfers retry without treating local IO errors as network errors.
- Slow-file total budget increased to 30 minutes; progress persistence is throttled.
- Personal-instance launch now prepares the account skin for compatible CustomSkinLoader installations. Vanilla does not gain custom skin support automatically; no mod is silently installed.
- Failed cached-pack launch reports a verification category and bounded missing/changed managed file paths in the updater log. Verification is never bypassed.

GearMorph content is unchanged: no owner-approved replacement archive has been supplied. Minecraft/Java, live accounts, production game sessions, VPN routes and skin display in real games are not qualified by a build-only CI run. No production feed or signed update envelope is published by these candidate workflows.
