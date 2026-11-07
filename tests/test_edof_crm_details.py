import json
from unittest.mock import Mock

import pytest
from edof_gmail import Vault, connector_key
import edof_crm_details as details
import edof_directory as directory
from edof_server_browser import EDOF_HOST, API_PREFIX


def test_partial_directory_is_enriched_only_with_matching_read(tmp_path):
    private = Vault(tmp_path, connector_key('fixture-connector-key-for-this-test-only'))
    row = {"folder_id":"123456789", "first_name":"Éloïse", "last_name":"Exemple"}
    folder = row["folder_id"]
    target = "https://" + EDOF_HOST + API_PREFIX + folder
    raw = {"id":folder, "attendee":{"firstName":"Eloïse", "lastName":"EXEMPLE", "email":"apprenant@example.test",
           "phoneNumber":"0600000000", "secret":"private"}, "currentState":"notProcessed",
           "states":[{"state":"notProcessed","date":"2026-11-06"}], "trainingActionInfo":{
               "totalIncl":"0.0","vat":"1500.50","indicativeDuration":75,"hoursInCompany":0,
               "intituleRNCP":"Qualification","codeRNCP":"RNCP00000","sessionId":directory.SIRET+"_session"},
           "documents":[{"name":"convocation.pdf","url":"https://example.test/download?token=secret"}]}
    witness = Mock(method="GET", url="https://"+EDOF_HOST+API_PREFIX+"pad")
    witness.all_headers.return_value = {"Authorization":"fixture","unrelated":"secret"}
    reply = Mock(url=target, status=200)
    reply.body.return_value = json.dumps(raw).encode()
    context = Mock()
    context.request.get.return_value = reply
    details.request_read(private,"owner",folder)
    reads = details.fill(context,witness,private,"owner",{folder:row},EDOF_HOST,API_PREFIX)
    assert reads[0] == {"folder":folder,"price":True,"duration":True,"certification":True,"events":1,"contact":True}
    stored = private.get(details.record_key("owner",folder))
    assert stored["trainingActionInfo"]["totalIncl"] == "1500.50"
    assert stored["trainingActionInfo"]["hoursInCompany"] == "0"
    assert stored["attendee"]["email"] == "apprenant@example.test"
    assert stored["files"] == [{"name":"convocation.pdf"}]
    assert "secret" not in json.dumps(stored)
    assert details.known_details(private, "owner") == {folder}
    assert details.fill(context,witness,private,"owner",{folder:row},EDOF_HOST,API_PREFIX) == []
    context.request.get.assert_called_once()
    assert not context.request.get.call_args.kwargs["max_redirects"]
    assert details.project(raw,dict(row, last_name="Autre"),123) is None
    assert details.project(raw,dict(row, folder_id="111111"),123) is None
    with pytest.raises(directory.IncompleteDirectory):
        details.project({**raw,"trainingId":"autre_siret"},row,123)


def test_on_demand_read_outside_pending_without_other_session(tmp_path):
    private = Vault(tmp_path, connector_key('fixture-connector-key-for-this-test-only'))
    owner, folder = "worker","234567"
    private.put(directory.record_key(owner), {"checked":1, "rows":{folder:{
        "folder_id":folder,"first_name":"Jo","last_name":"Exemple","session_start_date":"2026-11-10","state":"accepted"}}})
    details.request_read(private,owner,folder)
    context = Mock()
    assert details.fill(context,Mock(method="GET",url="https://wrong.invalid"),private,owner,{},EDOF_HOST,API_PREFIX)==[]
    context.request.get.assert_not_called()
    witness=Mock(method="GET",url="https://"+EDOF_HOST+API_PREFIX+"pad")
    witness.all_headers.return_value={}
    raw={"id":folder,"attendee":{"firstName":"Jo","lastName":"Exemple"},"currentState":"accepted"}
    response=Mock(status=200,url="https://"+EDOF_HOST+API_PREFIX+folder)
    response.body.return_value=json.dumps(raw).encode()
    context.request.get.return_value=response
    assert details.fill(context,witness,private,owner,{},EDOF_HOST,API_PREFIX)[0]["folder"] == folder
    assert "files" not in private.get(details.record_key(owner,folder))
