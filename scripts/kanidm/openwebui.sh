#!/bin/bash

kanidm group create openwebui_users
kanidm group create openwebui_admins

kanidm system oauth2 create openwebui OpenwebUI https://openwebui.moyer.wtf
kanidm system oauth2 del-redirect-url openwebui https://openwebui.moyer.wtf/openwebui/oauth/oidc/callback
kanidm system oauth2 update-scope-map openwebui openwebui_users openid email profile groups
kanidm system oauth2 update-scope-map openwebui openwebui_admins openid email profile groups
kanidm system oauth2 warning-insecure-client-disable-pkce openwebui

kanidm group add-members openwebui_users tmoyer
kanidm group add-members openwebui_admins tmoyer

kanidm system oauth2 show-basic-secret openwebui
