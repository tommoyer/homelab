#!/bin/bash

kanidm group create grafana_users
kanidm group create grafana_admins

kanidm system oauth2 create grafana Grafana https://grafana.priv.moyer.wtf
kanidm system oauth2 add-redirect-url grafana https://grafana.priv.moyer.wtf/login/generic_oauth
kanidm system oauth2 add-redirect-url grafana http://grafana.priv.moyer.wtf/login/generic_oauth
kanidm system oauth2 update-scope-map grafana grafana_users openid email profile groups
kanidm system oauth2 update-scope-map grafana grafana_admins openid email profile groups

kanidm group add-members grafana_users tmoyer
kanidm group add-members grafana_admins tmoyer

kanidm system oauth2 warning-insecure-client-disable-pkce grafana

kanidm system oauth2 update-claim-map-join grafana grafana_role array
kanidm system oauth2 update-claim-map grafana grafana_role grafana_admins Editor
kanidm system oauth2 update-claim-map grafana grafana_role grafana_users Viewer

kanidm system oauth2 show-basic-secret grafana
