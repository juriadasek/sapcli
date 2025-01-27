#!/usr/bin/env python3

import json
import unittest
from unittest.mock import Mock, call, patch, PropertyMock

from sap.rest.errors import HTTPRequestError, UnauthorizedError

import sap.rest.gcts
import sap.rest.gcts.remote_repo
import sap.rest.gcts.simple
import sap.rest.gcts.sugar

from mock import Request, Response, RESTConnection, make_gcts_log_error
from mock import GCTSLogBuilder as LogBuilder


class TestgCTSUtils(unittest.TestCase):

    def test_parse_url_https_git(self):
        package = sap.rest.gcts.package_name_from_url('https://example.org/foo/community.sap.git')
        self.assertEqual(package, 'community.sap')

    def test_parse_url_https(self):
        package = sap.rest.gcts.package_name_from_url('https://example.org/foo/git.no.suffix')
        self.assertEqual(package, 'git.no.suffix')


class TestGCSTRequestError(unittest.TestCase):

    def test_str_and_repr(self):
        log_builder = LogBuilder()
        messages = log_builder.log_error(make_gcts_log_error('Exists')).log_exception('Message', 'EEXIST').get_contents()
        ex = sap.rest.gcts.errors.GCTSRequestError(messages)

        self.assertEqual(str(ex), 'gCTS exception: Message')
        self.assertEqual(repr(ex), 'gCTS exception: Message')


class TestGCTSExceptionFactory(unittest.TestCase):

    def test_not_json_response(self):
        req = Request(method='GET', adt_uri='/epic/success', headers=None, body=None, params=None)
        res = Response(status_code=401, text='Not JSON')

        orig_error = UnauthorizedError(req, res, 'foo')
        new_error = sap.rest.gcts.errors.exception_from_http_error(orig_error)

        self.assertEqual(new_error, orig_error)

    def test_repository_does_not_exist(self):
        messages = {'exception': 'No relation between system and repository'}
        req = Request(method='GET', adt_uri='/epic/success', headers=None, body=None, params=None)
        res = Response.with_json(status_code=500, json=messages)

        orig_error = HTTPRequestError(req, res)
        new_error = sap.rest.gcts.errors.exception_from_http_error(orig_error)

        expected_error = sap.rest.gcts.errors.GCTSRepoNotExistsError(messages)

        self.assertEqual(str(new_error), str(expected_error))


class GCTSTestSetUp:

    def setUp(self):
        self.repo_url = 'https://example.com/git/repo'
        self.repo_rid = 'repo-id'
        self.repo_name = 'the repo name'
        self.repo_vsid = '6IT'
        self.repo_data = {
            'rid': self.repo_rid,
            'name': self.repo_rid,
            'role': 'SOURCE',
            'type': 'GITHUB',
            'vsid': '6IT',
            'url': self.repo_url,
            'connection': 'ssl',
        }

        self.repo_request ={
            'repository': self.repo_rid,
            'data': {
                'rid': self.repo_rid,
                'name': self.repo_rid,
                'role': 'SOURCE',
                'type': 'GITHUB',
                'vsid': '6IT',
                'url': self.repo_url,
                'connection': 'ssl',
            }
        }

        self.repo_server_data = dict(self.repo_data)
        self.repo_server_data['branch'] = 'the_branch'
        self.repo_server_data['currentCommit'] = 'FEDCBA9876543210'
        self.repo_server_data['status'] = 'READY'
        self.repo_server_data['config'] = [
            {'key': 'VCS_CONNECTION', 'value': 'SSL', 'category': 'Connection'},
            {'key': 'CLIENT_VCS_URI', 'category': 'Repository'}
        ]

        self.conn = RESTConnection()


class TestGCTSRepostiroy(GCTSTestSetUp, unittest.TestCase):

    def test_wipe_data(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data={})
        repo.wipe_data()
        self.assertIsNone(repo._data)

    def test_ctor_no_data(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        self.assertEqual(repo._http.connection, self.conn)
        self.assertEqual(repo.rid, self.repo_rid)
        self.assertIsNone(repo._data)

    def test_ctor_with_data(self):
        data = {}

        repo = sap.rest.gcts.remote_repo.Repository(None, self.repo_rid, data=data)

        self.assertIsNone(repo._http.connection)
        self.assertEqual(repo.rid, self.repo_rid)
        self.assertIsNotNone(repo._data)

    def test_properties_cached(self):
        repo = sap.rest.gcts.remote_repo.Repository(None, self.repo_rid, data=self.repo_server_data)

        self.assertEqual(repo.status, self.repo_server_data['status'])
        self.assertEqual(repo.rid, self.repo_server_data['rid'])
        self.assertEqual(repo.url, self.repo_server_data['url'])
        self.assertEqual(repo.branch, self.repo_server_data['branch'])
        self.assertEqual(repo.configuration, {'VCS_CONNECTION': 'SSL', 'CLIENT_VCS_URI': ''})

    def test_properties_fetch(self):
        response = {'result': self.repo_server_data}

        self.conn.set_responses([Response.with_json(json=response, status_code=200)])

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        self.assertEqual(repo.status, self.repo_server_data['status'])
        self.assertEqual(repo.rid, self.repo_server_data['rid'])
        self.assertEqual(repo.url, self.repo_server_data['url'])
        self.assertEqual(repo.branch, self.repo_server_data['branch'])

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}'), self)

    # exactly the same as test_properties_fetch but with 500 as status
    # testing gCTS' behavior for repos whose remote does not exist
    def test_properties_fetch_with_500(self):
        response = {'result': self.repo_server_data}

        self.conn.set_responses([Response.with_json(json=response, status_code=500)])

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        self.assertEqual(repo.status, self.repo_server_data['status'])
        self.assertEqual(repo.rid, self.repo_server_data['rid'])
        self.assertEqual(repo.url, self.repo_server_data['url'])
        self.assertEqual(repo.branch, self.repo_server_data['branch'])

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}'), self)

    def test_properties_fetch_error(self):
        messages = LogBuilder(exception='Get Repo Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            unused = repo.name

        self.assertEqual(str(caught.exception), 'gCTS exception: Get Repo Error')

    def test_create_no_self_data_no_config(self):
        self.conn.set_responses(
            Response.with_json(status_code=201, json={'repository': self.repo_server_data})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        repo.create(self.repo_url, self.repo_vsid)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository', body=self.repo_request, accept='application/json'),
                                       self, json_body=True)

    def test_create_with_config_instance_none(self):
        self.conn.set_responses(
            Response.with_json(status_code=201, json={'repository': self.repo_server_data})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        repo.create(self.repo_url, self.repo_vsid, config={'THE_KEY': 'THE_VALUE'})

        repo_request = dict(self.repo_request)
        repo_request['data']['config'] = [{
            'key': 'THE_KEY', 'value': 'THE_VALUE'
        }]

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository', body=repo_request, accept='application/json'),
                                       self, json_body=True)

    def test_create_with_config_update_instance(self):
        self.conn.set_responses(
            Response.with_json(status_code=201, json={'repository': self.repo_server_data})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data={
            'config': [
                {'key': 'first_key', 'value': 'first_value'},
                {'key': 'third_key', 'value': 'third_value'}
            ]
        })

        repo.create(self.repo_url, self.repo_vsid, config={'second_key': 'second_value', 'third_key': 'fourth_value'})

        repo_request = dict(self.repo_request)
        repo_request['data']['config'] = [
            {'key': 'first_key', 'value': 'first_value'},
            {'key': 'third_key', 'value': 'fourth_value'},
            {'key': 'second_key', 'value': 'second_value'},
        ]

        self.maxDiff = None
        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository', body=repo_request, accept='application/json'),
                                       self, json_body=True)

    def test_create_with_role_and_type(self):
        self.conn.set_responses(
            Response.with_json(status_code=201, json={'repository': self.repo_server_data})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        repo.create(self.repo_url, self.repo_vsid, role='TARGET', typ='GIT')

        repo_request = dict(self.repo_request)
        repo_request['data']['role'] = 'TARGET'
        repo_request['data']['type'] = 'GIT'

        self.maxDiff = None
        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository', body=repo_request, accept='application/json'),
                                       self, json_body=True)

    # Covered by TestgCTSSimpleClone
    #def test_create_generic_error(self):
    #    pass

    # Covered by TestgCTSSimpleClone
    #def test_create_already_exists_error(self):
    #    pass

    def test_set_config_success(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        repo.set_config('THE_KEY', 'the value')
        self.assertEqual(repo.get_config('THE_KEY'), 'the value')

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository/{self.repo_rid}/config', body={'key': 'THE_KEY', 'value': 'the value'}), self, json_body=True)

    def test_set_config_success_overwrite(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.set_config('VCS_CONNECTION', 'git')
        self.assertEqual(repo.get_config('VCS_CONNECTION'), 'git')

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post_json(uri=f'repository/{self.repo_rid}/config', body={'key': 'VCS_CONNECTION', 'value': 'git'}), self, json_body=True)

    def test_set_config_error(self):
        messages = LogBuilder(exception='Set Config Error').get_contents()

        self.conn.set_responses(Response.with_json(status_code=500, json=messages))
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.set_config('THE_KEY', 'the value')

        self.assertEqual(str(caught.exception), 'gCTS exception: Set Config Error')

    def test_get_config_cached_ok(self):
        repo = sap.rest.gcts.remote_repo.Repository(None, self.repo_rid, data={
            'config': [
                {'key': 'THE_KEY', 'value': 'the value', 'category': 'connection'}
            ]
        })

        value = repo.get_config('THE_KEY')
        self.assertEqual(value, 'the value')

    def test_get_config_no_config_ok(self):
        self.conn.set_responses(Response.with_json(status_code=200, json={'result':self.repo_server_data}))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        # This will fetch repo data from the server
        value = repo.get_config('VCS_CONNECTION')
        self.assertEqual(value, 'SSL')

        # The second request does not causes an HTTP request
        value = repo.get_config('VCS_CONNECTION')
        self.assertEqual(value, 'SSL')

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}'), self)

    def test_get_config_no_key_ok(self):
        self.conn.set_responses(Response.with_json(status_code=200, json={'result': {'value': 'the value'}}))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)

        # This will fetch the configruation key value from the server
        value = repo.get_config('THE_KEY')
        self.assertEqual(value, 'the value')

        # The second request does not causes an HTTP request
        value = repo.get_config('THE_KEY')
        self.assertEqual(value, 'the value')

        # The update of keys did not break the cache
        value = repo.get_config('VCS_CONNECTION')
        self.assertEqual(value, 'SSL')

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}/config/THE_KEY'), self)

    def test_get_config_no_value_ok(self):
        self.conn.set_responses(Response.with_json(status_code=200, json={'result': {}}))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        value = repo.get_config('THE_KEY')

        self.assertIsNone(value)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}/config/THE_KEY'), self)

    def test_get_config_error(self):
        messages = LogBuilder(exception='Get Config Error').get_contents()

        self.conn.set_responses(Response.with_json(status_code=500, json=messages))
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)

        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.get_config('THE_KEY')

        self.assertEqual(str(caught.exception), 'gCTS exception: Get Config Error')

    def test_repo_without_config(self):
        data = dict(self.repo_server_data)
        del data['config']

        self.conn.set_responses(Response.with_json(status_code=200, json={"result": data}))
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)

        self.assertEqual(repo.configuration, {})

    def test_delete_config_ok(self):
        key = 'CLIENT_VCS_URI'
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.delete_config(key)

        expected_repo_config = {'VCS_CONNECTION': 'SSL', 'CLIENT_VCS_URI': ''}
        self.assertEqual(repo.configuration, expected_repo_config)
        self.conn.execs[0].assertEqual(Request.delete(f'repository/{self.repo_rid}/config/{key}'), self)

    def test_delete_config_key_not_in_config_ok(self):
        key = 'THE_KEY'
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.delete_config(key)

        self.conn.execs[0].assertEqual(Request.delete(f'repository/{self.repo_rid}/config/{key}'), self)

    def test_clone_ok(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.clone()

        self.assertIsNone(repo._data)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.post(uri=f'repository/{self.repo_rid}/clone'), self)

    def test_clone_error(self):
        messages = LogBuilder(exception='Clone Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.clone()

        self.assertIsNotNone(repo._data)
        self.assertEqual(str(caught.exception), 'gCTS exception: Clone Error')

    def test_checkout_ok(self):
        self.conn.set_responses(Response.with_json(status_code=200, json={'result': {
            'fromCommit': '123',
            'toCommit': '456'
        }}))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.checkout('the_other_branch')

        self.assertIsNone(repo._data)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get(adt_uri=f'repository/{self.repo_rid}/branches/the_branch/switch', params={'branch': 'the_other_branch'}), self)

    def test_checkout_error(self):
        messages = LogBuilder(exception='Checkout Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.checkout('the_other_branch')

        self.assertIsNotNone(repo._data)
        self.assertEqual(str(caught.exception), 'gCTS exception: Checkout Error')

    def test_delete_ok(self):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        repo.delete()

        self.assertIsNone(repo._data)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request(method='DELETE', adt_uri=f'repository/{self.repo_rid}', params=None, headers=None, body=None), self)

    def test_delete_error(self):
        messages = LogBuilder(exception='Delete Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.delete()

        self.assertIsNotNone(repo._data)
        self.assertEqual(str(caught.exception), 'gCTS exception: Delete Error')

    def test_log_ok(self):
        exp_commits = [{'id': '123'}]

        self.conn.set_responses(
            Response.with_json(status_code=200, json={
                'commits': exp_commits
            })
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        act_commits = repo.log()

        self.assertIsNotNone(repo._data)
        self.assertEqual(act_commits, exp_commits)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}/getCommit'), self)

    def test_log_error(self):
        messages = LogBuilder(exception='Log Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.log()

        self.assertIsNotNone(repo._data)
        self.assertEqual(str(caught.exception), 'gCTS exception: Log Error')

    def test_pull(self):
        exp_log = {
            'fromCommit': '123',
            'toCommit': '456'
        }

        self.conn.set_responses(
            Response.with_json(status_code=200, json=exp_log )
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        act_log = repo.pull()

        self.assertIsNone(repo._data)
        self.assertEqual(act_log, exp_log)

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}/pullByCommit'), self)

    def test_pull_error(self):
        messages = LogBuilder(exception='Pull Error').get_contents()
        self.conn.set_responses(
            Response.with_json(status_code=500, json=messages)
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            repo.pull()

        self.assertIsNotNone(repo._data)
        self.assertEqual(str(caught.exception), 'gCTS exception: Pull Error')

    def assert_repo_activities(self, query_params, expected_result, expected_params):
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        result = repo.activities(query_params)

        self.assertEqual(result, expected_result)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}/getHistory',
                                                        params=expected_params), self)

    def test_activities_default_params(self):
        expected_params = {'limit': '10', 'offset': '0'}
        expected_result = ['activity']
        query_params = sap.rest.gcts.remote_repo.RepoActivitiesQueryParams()
        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': expected_result})
        )

        self.assert_repo_activities(query_params, expected_result, expected_params)

    def test_activities_all_params(self):
        expected_params = {'limit': '15', 'offset': '10', 'toCommit': '123', 'fromCommit': '456', 'type': 'CLONE'}
        expected_result = ['activity']

        query_params = sap.rest.gcts.remote_repo.RepoActivitiesQueryParams().set_limit(15).set_offset(10)\
            .set_tocommit('123').set_fromcommit('456').set_operation('CLONE')
        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': expected_result})
        )

        self.assert_repo_activities(query_params, expected_result, expected_params)

    def test_activities_empty_response(self):
        expected_params = {'limit': '10', 'offset': '0'}
        expected_result = []

        query_params = sap.rest.gcts.remote_repo.RepoActivitiesQueryParams()
        self.conn.set_responses(
            Response.with_json(status_code=200, json={})
        )

        self.assert_repo_activities(query_params, expected_result, expected_params)

    def test_activities_empty_result(self):
        query_params = sap.rest.gcts.remote_repo.RepoActivitiesQueryParams()
        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': []})
        )

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
            repo.activities(query_params)

        self.assertEqual(str(cm.exception), 'A successful gcts getHistory request did not return result')

    def test_commit_transports(self):
        corrnr = 'CORRNR'
        message = 'Message'
        description = 'Description'

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        response = repo.commit_transport(corrnr, message, description=description)

        self.conn.execs[0].assertEqual(
            Request.post_json(
                uri=f'repository/{self.repo_rid}/commit',
                body={
                    'message': message,
                    'autoPush': 'true',
                    'objects': [{'object': corrnr, 'type': 'TRANSPORT'}],
                    'description': description
                }
            ),
            self
        )

        self.assertIsNone(repo._data)

    def test_commit_package(self):
        package = 'Package'
        message = 'Message'
        description = 'Description'

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=self.repo_server_data)
        response = repo.commit_package(package, message, description=description)

        self.conn.execs[0].assertEqual(
            Request.post_json(
                uri=f'repository/{self.repo_rid}/commit',
                body={
                    'message': message,
                    'autoPush': 'true',
                    'objects': [{'object': package, 'type': 'FULL_PACKAGE'}],
                    'description': description
                }
            ),
            self
        )

        self.assertIsNone(repo._data)

    def test_set_url_change(self):
        CALL_ID_FETCH_REPO_DATA = 0
        CALL_ID_SET_URL = 1
        NEW_URL = 'https://random.github.org/awesome/success'

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
            Response.ok()
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)
        response = repo.set_url(NEW_URL)

        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(
            Request.get_json(uri=f'repository/{self.repo_rid}'),
            self
        )

        request_with_url = {'url': NEW_URL}

        self.conn.execs[CALL_ID_SET_URL].assertEqual(
            Request.post_json(
                uri=f'repository/{self.repo_rid}',
                body=request_with_url
            ),
            self
        )

    def test_set_url_nochange(self):
        CALL_ID_FETCH_REPO_DATA = 0
        NEW_URL = self.repo_server_data['url']

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)
        response = repo.set_url(NEW_URL)

        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(
            Request.get_json(uri=f'repository/{self.repo_rid}'),
            self
        )

        self.assertIsNone(response)

    def test_set_item(self):
        CALL_ID_FETCH_REPO_DATA = 0
        CALL_ID_SET_URL = 1

        property_name = 'name'
        new_value = 'new_name'

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
            Response.ok()
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)
        response = repo.set_item(property_name, new_value)

        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(
            Request.get_json(uri=f'repository/{self.repo_rid}'),
            self
        )

        expected_request_body = {property_name: new_value}

        self.conn.execs[CALL_ID_SET_URL].assertEqual(
            Request.post_json(
                uri=f'repository/{self.repo_rid}',
                body=expected_request_body
            ),
            self
        )

        self.assertIsNotNone(response)

    def test_set_item_incorrect_property(self):
        property_name = 'incorrect_property'

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            repo.set_item(property_name, 'value')

        self.assertEqual(self.conn.execs, [])
        self.assertEqual(str(cm.exception), f'Cannot edit property "{property_name}".')

    def test_set_item_nochange(self):
        CALL_ID_FETCH_REPO_DATA = 0

        property_name = 'rid'
        new_value = self.repo_rid

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)
        response = repo.set_item(property_name, new_value)

        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(
            Request.get_json(uri=f'repository/{self.repo_rid}'),
            self
        )

        self.assertIsNone(response)

    def test_set_role(self):
        CALL_ID_SET_ROLE = 1

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
            Response.ok()
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=None)
        response = repo.set_role('TARGET')

        self.conn.execs[CALL_ID_SET_ROLE].assertEqual(
            Request.post_json(
                uri=f'repository/{self.repo_rid}',
                body={"role": "TARGET"}
            ),
            self
        )

    def test_create_branch(self):
        branch_name = 'branch'
        expected_response = {
            'name': branch_name,
            'type': 'active',
            'isSymbolic': False,
            'isPeeled': False,
            'ref': f'/refs/heads/{branch_name}',
        }

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'branch': expected_response})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        response = repo.create_branch(branch_name)

        self.conn.execs[0].assertEqual(
            Request.post_json(f'repository/{self.repo_rid}/branches', body={
                'branch': branch_name,
                'type': 'global',
                'isSymbolic': False,
                'isPeeled': False,
            }),
            self
        )
        self.assertEqual(response, expected_response)

    def test_create_branch_all_params(self):
        branch_name = 'branch'
        expected_response = {
            'name': branch_name,
            'type': 'active',
            'isSymbolic': True,
            'isPeeled': True,
            'ref': f'/refs/heads/{branch_name}',
        }

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'branch': expected_response})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        response = repo.create_branch(branch_name, symbolic=True, peeled=True, local_only=True)

        self.conn.execs[0].assertEqual(
            Request.post_json(f'repository/{self.repo_rid}/branches', body={
                'branch': branch_name,
                'type': 'local',
                'isSymbolic': True,
                'isPeeled': True,
            }),
            self,
        )
        self.assertEqual(response, expected_response)

    def test_delete_branch(self):
        branch_name = 'branch'

        self.conn.set_responses(
            Response.with_json(status_code=200, json={})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        response = repo.delete_branch(branch_name)

        self.conn.execs[0].assertEqual(
            Request.delete(f'repository/{self.repo_rid}/branches/{branch_name}'),
            self,
        )
        self.assertEqual(response, {})

    def test_list_branches(self):
        branches = [{'name': 'branch1', 'type': 'active', 'isSymbolic': False, 'isPeeled': False,
                     'ref': 'refs/heads/branch1'},
                    {'name': 'branch1', 'type': 'local', 'isSymbolic': False, 'isPeeled': False,
                     'ref': 'refs/heads/branch1'},
                    {'name': 'branch1', 'type': 'remote', 'isSymbolic': False, 'isPeeled': False,
                     'ref': 'refs/remotes/origin/branch1'}]

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'branches': branches})
        )
        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        response = repo.list_branches()

        self.conn.execs[0].assertEqual(
            Request.get_json(f'repository/{self.repo_rid}/branches'),
            self
        )
        self.assertEqual(response, branches)

    def test_list_branches_wrong_response(self):
        self.conn.set_responses(
            Response.with_json(status_code=200, json={})
        )

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid)
        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            repo.list_branches()

        self.assertEqual(str(cm.exception), "gCTS response does not contain 'branches'")


class TestRepoActivitiesQueryParams(unittest.TestCase):

    def setUp(self):
        self.params = sap.rest.gcts.remote_repo.RepoActivitiesQueryParams()

    def test_set_operation_invalid(self):
        with self.assertRaises(sap.rest.errors.SAPCliError) as caught:
            self.params.set_operation('FOO')

        self.assertEqual(str(caught.exception), 'Invalid gCTS Activity Operation: FOO')

    def test_set_operation_valid(self):
        for operation in sap.rest.gcts.remote_repo.RepoActivitiesQueryParams.allowed_operations():
            self.params.set_operation(operation)


class TestgCTSSimpleAPI(GCTSTestSetUp, unittest.TestCase):

    def test_simple_clone_success(self):
        CALL_ID_CREATE = 0
        CALL_ID_CLONE = 1

        repository = dict(self.repo_server_data)
        repository['status'] = 'CREATED'

        self.conn.set_responses(
            Response.with_json(status_code=201, json={'repository': repository}),
            Response.ok()
        )

        sap.rest.gcts.simple.clone(
            self.conn,
            self.repo_url,
            self.repo_rid,
            vcs_token='THE_TOKEN'
        )

        data = dict(self.repo_data)
        data['config'] = [
            {'key': 'VCS_TARGET_DIR', 'value': 'src/'},
            {'key': 'CLIENT_VCS_AUTH_TOKEN', 'value': 'THE_TOKEN'}
        ]

        request_load = {
            'repository': self.repo_rid,
            'data': data
        }

        self.assertEqual(len(self.conn.execs), 2)

        self.conn.execs[CALL_ID_CREATE].assertEqual(Request.post_json(uri='repository', body=request_load, accept='application/json'), self, json_body=True)
        self.conn.execs[CALL_ID_CLONE].assertEqual(Request.post(uri=f'repository/{self.repo_rid}/clone'), self)

    @patch('sap.rest.gcts.remote_repo.Repository.is_cloned', new_callable=PropertyMock)
    @patch('sap.rest.gcts.remote_repo.Repository.create')
    def test_simple_clone_passing_parameters(self, fake_create, fake_is_cloned):
        fake_is_cloned.return_value = True

        def assertPassedParameters(url, vsid, config=None, role=None, typ=None):
            self.assertEqual(vsid, '0ZZ')
            self.assertEqual(role, 'TARGET')
            self.assertEqual(typ, 'GIT')
            self.assertEqual(config, {'VCS_TARGET_DIR': 'foo/', 'CLIENT_VCS_AUTH_TOKEN': 'THE_TOKEN'})

        fake_create.side_effect = assertPassedParameters

        sap.rest.gcts.simple.clone(
            self.conn,
            self.repo_url,
            self.repo_rid,
            vcs_token='THE_TOKEN',
            vsid='0ZZ',
            start_dir='foo/',
            role='TARGET',
            typ='GIT'
        )

    def test_simple_clone_without_params_create_fail(self):
        log_builder = LogBuilder()
        messages = log_builder.log_error(make_gcts_log_error('Failure')).log_exception('Message', 'EERROR').get_contents()

        self.conn.set_responses([Response.with_json(status_code=500, json=messages)])

        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            sap.rest.gcts.simple.clone(self.conn, self.repo_url, self.repo_rid)

        self.assertEqual(str(caught.exception), 'gCTS exception: Message')

    def test_simple_clone_without_params_create_exists(self):
        log_builder = LogBuilder()
        log_builder.log_error(make_gcts_log_error('20200923111743: Error action CREATE_REPOSITORY Repository already exists'))
        log_builder.log_exception('Cannot create', 'EEXIST').get_contents()
        messages = log_builder.get_contents()

        self.conn.set_responses([Response.with_json(status_code=500, json=messages)])

        with self.assertRaises(sap.rest.gcts.errors.GCTSRepoAlreadyExistsError) as caught:
            sap.rest.gcts.simple.clone(self.conn, self.repo_url, self.repo_rid)

        self.assertEqual(str(caught.exception), 'gCTS exception: Cannot create')

    def test_simple_clone_without_params_create_exists_continue(self):
        CALL_ID_FETCH_REPO_DATA = 1

        log_builder = LogBuilder()
        log_builder.log_error(make_gcts_log_error('20200923111743: Error action CREATE_REPOSITORY Repository already exists'))
        log_builder.log_exception('Cannot create', 'EEXIST').get_contents()
        messages = log_builder.get_contents()

        new_repo_data = dict(self.repo_server_data)
        new_repo_data['status'] = 'CREATED'

        self.conn.set_responses([
            Response.with_json(status_code=500, json=messages),
            Response.with_json(status_code=200, json={'result': new_repo_data}),
            Response.ok()
        ])

        repo = sap.rest.gcts.simple.clone(self.conn, self.repo_url, self.repo_rid, error_exists=False)
        self.assertIsNotNone(repo)
        self.assertEqual(len(self.conn.execs), 3)
        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}'), self)

    def test_simple_clone_without_params_create_exists_continue_cloned(self):
        CALL_ID_FETCH_REPO_DATA = 1

        log_builder = LogBuilder()
        log_builder.log_error(make_gcts_log_error('20200923111743: Error action CREATE_REPOSITORY Repository already exists'))
        log_builder.log_exception('Cannot create', 'EEXIST').get_contents()
        messages = log_builder.get_contents()

        self.assertEqual(self.repo_server_data['status'], 'READY')

        self.conn.set_responses([
            Response.with_json(status_code=500, json=messages),
            Response.with_json(status_code=200, json={'result': self.repo_server_data}),
        ])

        repo = sap.rest.gcts.simple.clone(self.conn, self.repo_url, self.repo_rid, error_exists=False)
        self.assertIsNotNone(repo)

        self.assertEqual(len(self.conn.execs), 2)
        self.conn.execs[CALL_ID_FETCH_REPO_DATA].assertEqual(Request.get_json(uri=f'repository/{self.repo_rid}'), self)

    @patch('sap.rest.gcts.simple._mod_log')
    def test_simple_wait_for_clone(self, fake_mod_log):
        repository = dict(self.repo_server_data)
        repository['status'] = 'CREATED'

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=repository)
        repo.wipe_data = Mock(side_effect=repo.wipe_data)

        self.conn.set_responses([
            Response.with_json(status_code=200, json={'result': self.repo_server_data})
        ])

        sap.rest.gcts.simple.wait_for_clone(repo, 10, None)
        repo.wipe_data.assert_called_once()
        fake_mod_log.return_value.debug.assert_not_called()

    @patch('sap.rest.gcts.simple._mod_log')
    def test_simple_wait_for_clone_with_retries(self, fake_mod_log):
        repository = dict(self.repo_server_data)
        repository['status'] = 'CREATED'

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=repository)
        repo.wipe_data = Mock(side_effect=repo.wipe_data)

        self.conn.set_responses([
            Response(status_code=500, text='Test HTTP Request Exception'),
            Response.with_json(status_code=200, json={'result': repository}),
            Response.with_json(status_code=200, json={'result': self.repo_server_data})
        ])

        sap.rest.gcts.simple.wait_for_clone(repo, 10, None)
        self.assertEqual(repo.wipe_data.mock_calls, [call(), call(), call()])
        fake_mod_log.return_value.debug.assert_called_once_with('Failed to get status of the repository %s', repo.name)

    @patch('sap.rest.gcts.simple.time.time')
    def test_simple_wait_for_clone_timeout(self, fake_time):
        repository = dict(self.repo_server_data)
        repository['status'] = 'CREATED'

        fake_time.side_effect = [0, 1, 2]

        self.conn.set_responses([
            Response.with_json(status_code=200, json={'result': repository}),
        ])

        repo = sap.rest.gcts.remote_repo.Repository(self.conn, self.repo_rid, data=repository)
        http_error = HTTPRequestError(None, Response(status_code=500, text='Test HTTP Request Exception'))

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            sap.rest.gcts.simple.wait_for_clone(repo, 2, http_error)

        self.assertEqual(str(cm.exception), 'Waiting for the repository to be in READY state timed out\n'
                                            '500\nTest HTTP Request Exception')

    def test_simple_fetch_no_repo(self):
        self.conn.set_responses(
            Response.with_json(status_code=200, json={})
        )

        repos = sap.rest.gcts.simple.fetch_repos(self.conn)
        self.assertEqual(len(repos), 0)

    def test_simple_fetch_ok(self):
        REPO_ONE_ID=0
        repo_one = dict(self.repo_server_data)
        repo_one['name'] = repo_one['rid'] = 'one'

        REPO_TWO_ID=1
        repo_two = dict(self.repo_server_data)
        repo_two['name'] = repo_two['rid'] = 'two'

        self.conn.set_responses(
            Response.with_json(status_code=200, json={'result':
                [repo_one, repo_two]
            })
        )

        repos = sap.rest.gcts.simple.fetch_repos(self.conn)

        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[REPO_ONE_ID].name, 'one')
        self.assertEqual(repos[REPO_TWO_ID].name, 'two')

        self.assertEqual(len(self.conn.execs), 1)
        self.conn.execs[0].assertEqual(Request.get_json(uri=f'repository'), self)


    def test_simple_fetch_error(self):
        messages = LogBuilder(exception='Fetch Error').get_contents()
        self.conn.set_responses(Response.with_json(status_code=500, json=messages))

        with self.assertRaises(sap.rest.gcts.errors.GCTSRequestError) as caught:
            sap.rest.gcts.simple.fetch_repos(self.conn)

        self.assertEqual(str(caught.exception), 'gCTS exception: Fetch Error')

    @patch('sap.rest.gcts.simple.Repository')
    def test_simple_checkout_ok(self, fake_repository):
        fake_instance = Mock()
        fake_repository.return_value = fake_instance
        fake_instance.checkout = Mock()
        fake_instance.checkout.return_value = 'probe'

        response = sap.rest.gcts.simple.checkout(self.conn, 'the_new_branch', rid=self.repo_rid)
        fake_repository.assert_called_once_with(self.conn, self.repo_rid)
        fake_instance.checkout.assert_called_once_with('the_new_branch')
        self.assertEqual(response, 'probe')

    @patch('sap.rest.gcts.simple.Repository')
    def test_simple_delete_name(self, fake_repository):
        fake_instance = Mock()
        fake_repository.return_value = fake_instance
        fake_instance.delete = Mock()
        fake_instance.delete.return_value = 'probe'

        response = sap.rest.gcts.simple.delete(self.conn, rid=self.repo_rid)
        fake_repository.assert_called_once_with(self.conn, self.repo_rid)
        fake_instance.delete.assert_called_once_with()
        self.assertEqual(response, 'probe')

    def test_simple_delete_repo(self):
        fake_instance = Mock()
        fake_instance.delete.return_value = 'probe'

        response = sap.rest.gcts.simple.delete(None, repo=fake_instance)
        self.assertEqual(response, 'probe')

    @patch('sap.rest.gcts.simple.Repository')
    def test_simple_log_name(self, fake_repository):
        fake_instance = Mock()
        fake_repository.return_value = fake_instance
        fake_instance.log = Mock()
        fake_instance.log.return_value = 'probe'

        response = sap.rest.gcts.simple.log(self.conn, rid=self.repo_rid)
        fake_repository.assert_called_once_with(self.conn, self.repo_rid)
        fake_instance.log.assert_called_once_with()
        self.assertEqual(response, 'probe')

    def test_simple_log_repo(self):
        fake_instance = Mock()
        fake_instance.log = Mock()
        fake_instance.log.return_value = 'probe'

        response = sap.rest.gcts.simple.log(None, repo=fake_instance)
        self.assertEqual(response, 'probe')

    @patch('sap.rest.gcts.simple.Repository')
    def test_simple_pull_name(self, fake_repository):
        fake_instance = Mock()
        fake_repository.return_value = fake_instance
        fake_instance.pull = Mock()
        fake_instance.pull.return_value = 'probe'

        response = sap.rest.gcts.simple.pull(self.conn, rid=self.repo_rid)
        fake_repository.assert_called_once_with(self.conn, self.repo_rid)
        fake_instance.pull.assert_called_once_with()
        self.assertEqual(response, 'probe')

    def test_simple_pull_repo(self):
        fake_instance = Mock()
        fake_instance.pull = Mock()
        fake_instance.pull.return_value = 'probe'

        response = sap.rest.gcts.simple.pull(None, repo=fake_instance)
        self.assertEqual(response, 'probe')

    def test_simple_get_user_credentials(self):
        user_credentials = [{"domain": "url", "endpointType": "THETYPE", "subDomain": "api.url",
                             "endpoint": "https://api.url", "type": "token", "state": "false"}]

        self.conn.set_responses([
            Response.with_json(json={
                'user': {
                    'config': [{'key': 'USER_AUTH_CRED_ENDPOINTS', 'value': json.dumps(user_credentials)}]
                }
            })
        ])

        response = sap.rest.gcts.simple.get_user_credentials(self.conn)

        self.assertEqual(self.conn.mock_methods(), [('GET', 'user')])
        self.conn.execs[0].assertEqual(
            Request.get_json(uri='user'),
            self
        )

        self.assertEqual(response, user_credentials)

    def test_simple_get_user_credentials_no_user_data(self):
        self.conn.set_responses([
            Response.with_json(json={})
        ])

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            sap.rest.gcts.simple.get_user_credentials(self.conn)

        self.assertEqual(self.conn.mock_methods(), [('GET', 'user')])
        self.assertEqual(str(cm.exception), 'gCTS response does not contain \'user\'')

    def test_simple_get_user_credentials_no_config_data(self):
        self.conn.set_responses([
            Response.with_json(json={
                'user': {}
            })
        ])

        response = sap.rest.gcts.simple.get_user_credentials(self.conn)

        self.assertEqual(self.conn.mock_methods(), [('GET', 'user')])
        self.assertEqual(response, [])

    def test_simple_set_user_api_token(self):
        connection = RESTConnection()

        api_url = 'https://api.url/'
        token = 'THETOKEN'
        response = sap.rest.gcts.simple.set_user_api_token(connection, api_url, token)

        self.assertEqual(connection.mock_methods(), [('POST', 'user/credentials')])
        connection.execs[0].assertEqual(
            Request.post_json(
                uri='user/credentials',
                body={
                    'endpoint': api_url,
                    'user': '',
                    'password': '',
                    'token': token,
                    'type': 'token'
                }
            ),
            self
        )

        self.assertEqual(response, None)

    def test_simple_delete_user_credentials(self):
        api_url = 'https://api.url'
        response = sap.rest.gcts.simple.delete_user_credentials(self.conn, api_url)

        self.assertEqual(self.conn.mock_methods(), [('POST', 'user/credentials')])
        self.conn.execs[0].assertEqual(
            Request.post_json(
                uri='user/credentials',
                body={
                    'endpoint': api_url,
                    'user': '',
                    'password': '',
                    'token': '',
                    'type': 'none'
                }
            ),
            self
        )

        self.assertEqual(response, None)

    def test_simple_get_system_config_property(self):
        config_key = 'THE_KEY'
        expected_response = {
            'key': config_key,
            'value': 'the_value'
        }

        self.conn.set_responses([
            Response.with_json({'result': expected_response})
        ])

        response = sap.rest.gcts.simple.get_system_config_property(self.conn, config_key)
        self.assertEqual(response, expected_response)

        self.conn.execs[0].assertEqual(
            Request.get_json(
                uri=f'system/config/{config_key}',
            ),
            self
        )

    def test_simple_get_system_config_property_no_result(self):
        self.conn.set_responses([
            Response.with_json({})
        ])

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            sap.rest.gcts.simple.get_system_config_property(self.conn, 'THE_KEY')

        self.assertEqual(str(cm.exception), "gCTS response does not contain 'result'")

    def test_simple_list_system_config(self):
        expected_response = [
            {
                'key': 'THE_KEY1',
                'value': 'THE_VALUE1',
                'category': 'CATEGORY',
                'changedAt': 20220101000000,
                'changedBy': 'TEST',
            },
            {
                'key': 'THE_KEY2',
                'value': 'THE_VALUE2',
                'category': 'CATEGORY',
                'changedAt': 20220101000000,
                'changedBy': 'TEST',
            }
        ]
        self.conn.set_responses([
            Response.with_json({'result': {'config': expected_response}})
        ])

        response = sap.rest.gcts.simple.list_system_config(self.conn)
        self.assertEqual(response, expected_response)

        self.conn.execs[0].assertEqual(
            Request.get_json('system'),
            self
        )

    def test_simple_list_system_config_no_config(self):
        self.conn.set_responses([
            Response.with_json({'result': {}})
        ])

        response = sap.rest.gcts.simple.list_system_config(self.conn)
        self.assertEqual(response, [])

        self.conn.execs[0].assertEqual(
            Request.get_json('system'),
            self
        )

    def test_simple_list_system_config_no_result(self):
        self.conn.set_responses([
            Response.with_json({})
        ])

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            sap.rest.gcts.simple.list_system_config(self.conn)

        self.assertEqual(str(cm.exception), "gCTS response does not contain 'result'")

    def test_simple_set_system_config_property(self):
        config_key = 'THE_KEY'
        value = 'the_value'
        expected_response = {
            'key': config_key,
            'value': value
        }

        self.conn.set_responses([
            Response.with_json({'result': expected_response})
        ])

        response = sap.rest.gcts.simple.set_system_config_property(self.conn, config_key, value)
        self.assertEqual(response, expected_response)

        self.conn.execs[0].assertEqual(
            Request.post_json(
                uri='system/config',
                body={'key': config_key, 'value': value}
            ),
            self
        )

    def test_simple_set_system_config_property_no_result(self):
        self.conn.set_responses([
            Response.with_json({})
        ])

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            sap.rest.gcts.simple.set_system_config_property(self.conn, 'THE_KEY', 'the_value')

        self.assertEqual(str(cm.exception), "gCTS response does not contain 'result'")

    def test_simple_delete_system_config_property(self):
        config_key = 'THE_KEY'
        self.conn.set_responses([
            Response.with_json({})
        ])

        response = sap.rest.gcts.simple.delete_system_config_property(self.conn, config_key)
        self.assertEqual(response, {})

        self.conn.execs[0].assertEqual(
            Request.delete(
                uri=f'system/config/{config_key}',
                headers={'Accept': 'application/json'}
            ),
            self
        )


class TestgCTSSugar(GCTSTestSetUp, unittest.TestCase):

    def setUp(self):
        self.fake_repo = Mock()
        self.progress = sap.rest.gcts.sugar.LogSugarOperationProgress()
        self.new_branch = 'new_branch'

        self.fake_log_info = Mock()
        fake_get_logger = patch('sap.rest.gcts.sugar.get_logger').start()
        fake_get_logger.return_value.info = self.fake_log_info

    @patch.multiple(sap.rest.gcts.sugar.SugarOperationProgress, __abstractmethods__=set())
    def test_sugar_operation_progress(self):
        progress = sap.rest.gcts.sugar.SugarOperationProgress()

        self.assertEqual(progress.recover_message, None)

        with self.assertRaises(NotImplementedError):
            progress.update('message', 'recover_message')

        self.assertEqual(progress.recover_message, 'recover_message')

    def test_log_sugar_operation_progress(self):
        log_msg = 'Log message.'
        recover_msg = 'Recover message.'

        self.progress.update(log_msg, recover_message=recover_msg)

        self.assertEqual(self.progress.recover_message, recover_msg)
        self.fake_log_info.assert_called_once_with(log_msg)

    def test_abap_modifications_disabled_reset(self):
        self.fake_repo.get_config.return_value = ''

        with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo, self.progress):
            log_info_calls = [call('Disabling imports by setting the config VCS_NO_IMPORT = "X" ...'),
                              call('Successfully changed the config VCS_NO_IMPORT = "" -> "X"')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.fake_repo.set_config.assert_called_once_with('VCS_NO_IMPORT', 'X')
            self.assertEqual(self.progress.recover_message,
                             'Please set the configuration option VCS_NO_IMPORT = "" manually')

        log_info_calls += [call('Resetting the config VCS_NO_IMPORT = "" ...'),
                           call('Successfully reset the config VCS_NO_IMPORT = ""')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.fake_repo.set_config.assert_called_with('VCS_NO_IMPORT', '')
        self.assertEqual(self.progress.recover_message, None)

    def test_abap_modifications_disabled_reset_error(self):
        self.fake_repo.get_config.return_value = ''

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo, self.progress):
                self.fake_repo.set_config.side_effect = sap.rest.errors.SAPCliError('Set of configuration failed.')

        self.assertEqual(str(cm.exception), 'Set of configuration failed.')
        self.assertEqual(self.progress.recover_message,
                         'Please set the configuration option VCS_NO_IMPORT = "" manually')

    def test_abap_modifications_disabled_delete(self):
        self.fake_repo.get_config.return_value = None

        with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo, self.progress):
            log_info_calls = [call('Disabling imports by setting the config VCS_NO_IMPORT = "X" ...'),
                              call('Successfully added the config VCS_NO_IMPORT = "X"')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.fake_repo.set_config.assert_called_once_with('VCS_NO_IMPORT', 'X')
            self.assertEqual(self.progress.recover_message,
                             'Please delete the configuration option VCS_NO_IMPORT manually')

        log_info_calls += [call('Removing the config VCS_NO_IMPORT ...'),
                           call('Successfully removed the config VCS_NO_IMPORT')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.fake_repo.delete_config.assert_called_once_with('VCS_NO_IMPORT')
        self.assertEqual(self.progress.recover_message, None)

    def test_abap_modifications_disabled_delete_error(self):
        self.fake_repo.get_config.return_value = None

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo, self.progress):
                self.fake_repo.delete_config.side_effect = sap.rest.errors.SAPCliError('Delete config failed.')

        self.assertEqual(str(cm.exception), 'Delete config failed.')
        self.assertEqual(self.progress.recover_message,
                         'Please delete the configuration option VCS_NO_IMPORT manually')

    def test_abap_modifications_disabled_donothing(self):
        self.fake_repo.get_config.return_value = 'X'

        with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo, self.progress):
            log_info_calls = [call('Disabling imports by setting the config VCS_NO_IMPORT = "X" ...'),
                              call('The config VCS_NO_IMPORT was already set to "X"')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.fake_repo.set_config.assert_called_once_with('VCS_NO_IMPORT', 'X')

        log_info_calls += [call('The config VCS_NO_IMPORT has not beed changed')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.assertEqual(self.progress.recover_message, None)

    def test_abap_modifications_disabled_without_progress(self):
        self.fake_repo.get_config.return_value = 'X'

        with sap.rest.gcts.sugar.abap_modifications_disabled(self.fake_repo):
            log_info_calls = [call('Disabling imports by setting the config VCS_NO_IMPORT = "X" ...'),
                              call('The config VCS_NO_IMPORT was already set to "X"')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.fake_repo.set_config.assert_called_once_with('VCS_NO_IMPORT', 'X')

        log_info_calls += [call('The config VCS_NO_IMPORT has not beed changed')]
        self.fake_log_info.assert_has_calls(log_info_calls)

    def test_temporary_switched_branch_checkout(self):
        self.fake_repo.branch = 'old_branch'

        with sap.rest.gcts.sugar.temporary_switched_branch(self.fake_repo, self.new_branch, self.progress):
            log_info_calls = [call(f'Temporary switching to the updated branch {self.new_branch} ...'),
                              call(f'Successfully switched to the updated branch {self.new_branch}')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.fake_repo.checkout.assert_called_once_with(self.new_branch)
            self.assertEqual(self.progress.recover_message, 'Please switch to the branch old_branch manually')

        log_info_calls += [call('Restoring the previously active branch old_branch ...'),
                           call('Successfully restored the previously active branch old_branch')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.fake_repo.checkout.assert_called_with('old_branch')
        self.assertEqual(self.progress.recover_message, None)

    def test_temporary_switched_branch_checkout_error(self):
        self.fake_repo.branch = 'old_branch'

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            with sap.rest.gcts.sugar.temporary_switched_branch(self.fake_repo, self.new_branch, self.progress):
                self.fake_repo.checkout.side_effect = sap.rest.errors.SAPCliError('Checkout failed.')

        self.assertEqual(str(cm.exception), 'Checkout failed.')
        self.assertEqual(self.progress.recover_message,
                         'Please double check if the original branch old_branch is active')

    def test_temporary_switched_branch_pre_checkout_error(self):
        self.fake_repo.branch = 'old_branch'
        self.fake_repo.checkout.side_effect = sap.rest.errors.SAPCliError('Checkout failed.')

        with self.assertRaises(sap.rest.errors.SAPCliError) as cm:
            with sap.rest.gcts.sugar.temporary_switched_branch(self.fake_repo, self.new_branch, self.progress):
                self.assertEqual(self.progress.recover_message,
                                 'Please double check if the original branch old_branch is active')

        self.assertEqual(str(cm.exception), 'Checkout failed.')

    def test_temporary_switched_branch_donothing(self):
        self.fake_repo.branch = self.new_branch

        with sap.rest.gcts.sugar.temporary_switched_branch(self.fake_repo, self.new_branch, self.progress):
            log_info_calls = [call(f'The updated branch {self.new_branch} is already active')]
            self.fake_log_info.assert_has_calls(log_info_calls)
            self.assertEqual(self.progress.recover_message, None)

        log_info_calls += [call(f'The updated branch {self.new_branch} remains active')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.assertEqual(self.progress.recover_message, None)
        self.fake_repo.checkout.assert_not_called()

    def test_temporary_switched_branch_without_progress(self):
        self.fake_repo.branch = self.new_branch

        with sap.rest.gcts.sugar.temporary_switched_branch(self.fake_repo, self.new_branch):
            log_info_calls = [call(f'The updated branch {self.new_branch} is already active')]
            self.fake_log_info.assert_has_calls(log_info_calls)

        log_info_calls += [call(f'The updated branch {self.new_branch} remains active')]
        self.fake_log_info.assert_has_calls(log_info_calls)
        self.fake_repo.checkout.assert_not_called()
