#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import unicode_literals

from fuelweb_test.testrail.settings import logger
from fuelweb_test.testrail.testrail import APIClient
from fuelweb_test.testrail.testrail import APIError


class TestRailProject(object):
    """TestRailProject."""  # TODO documentation

    def __init__(self, url, user, password, project):
        self.client = APIClient(base_url=url)
        self.client.user = user
        self.client.password = password
        self.project = self._get_project(project)

    def _get_project(self, project_name):
        projects_uri = 'get_projects'
        projects = self.client.send_get(uri=projects_uri)
        for project in projects:
            if project['name'] == project_name:
                return project
        return None

    def test_run_struct(self, name, suite_id, milestone_id, description,
                        config_ids, include_all=True, assignedto=None,
                        case_ids=None):
        struct = {
            'name': name,
            'suite_id': suite_id,
            'milestone_id': milestone_id,
            'description': description,
            'include_all': include_all,
            'config_ids': config_ids
        }
        if case_ids:
            struct['include_all'] = False
            struct['case_ids'] = case_ids
        if assignedto:
            struct['assignedto_id'] = self.get_user(assignedto)['id']
        return struct

    def get_users(self):
        users_uri = 'get_users'
        return self.client.send_get(uri=users_uri)

    def get_user(self, user_id):
        user_uri = 'get_user/{user_id}'.format(user_id=user_id)
        return self.client.send_get(uri=user_uri)

    def get_user_by_name(self, name):
        for user in self.get_users():
            if user['name'] == name:
                return self.get_user(user_id=user['id'])

    def get_configs(self):
        configs_uri = 'get_configs/{project_id}'.format(
            project_id=self.project['id'])
        return self.client.send_get(configs_uri)

    def get_config(self, config_id):
        for configs in self.get_configs():
            for config in configs['configs']:
                if config['id'] == int(config_id):
                    return config

    def get_config_by_name(self, name):
        for config in self.get_configs():
            if config['name'] == name:
                return config

    def get_priorities(self):
        priorities_uri = 'get_priorities'
        return self.client.send_get(uri=priorities_uri)

    def get_milestones(self):
        milestones_uri = 'get_milestones/{project_id}'.format(
            project_id=self.project['id'])
        return self.client.send_get(uri=milestones_uri)

    def get_milestone(self, milestone_id):
        milestone_uri = 'get_milestone/{milestone_id}'.format(
            milestone_id=milestone_id)
        return self.client.send_get(uri=milestone_uri)

    def get_milestone_by_name(self, name):
        for milestone in self.get_milestones():
            if milestone['name'] == name:
                return self.get_milestone(milestone_id=milestone['id'])

    def get_suites(self):
        suites_uri = 'get_suites/{project_id}'.format(
            project_id=self.project['id'])
        return self.client.send_get(uri=suites_uri)

    def get_suite(self, suite_id):
        suite_uri = 'get_suite/{suite_id}'.format(suite_id=suite_id)
        return self.client.send_get(uri=suite_uri)

    def get_suite_by_name(self, name):
        for suite in self.get_suites():
            if suite['name'] == name:
                return self.get_suite(suite_id=suite['id'])

    def get_sections(self, suite_id):
        sections_uri = 'get_sections/{project_id}&suite_id={suite_id}'.format(
            project_id=self.project['id'],
            suite_id=suite_id
        )
        return self.client.send_get(sections_uri)

    def get_section(self, section_id):
        section_uri = 'get_section/{section_id}'.format(section_id=section_id)
        return self.client.send_get(section_uri)

    def get_section_by_name(self, suite_id, section_name):
        for section in self.get_sections(suite_id=suite_id):
            if section['name'] == section_name:
                return self.get_section(section_id=section['id'])

    def create_section(self, suite_id, name, parent_id=None):
        return self.client.send_post('add_section/' + str(self.project['id']),
                                     dict(suite_id=suite_id, name=name,
                                          parent_id=parent_id))

    def delete_section(self, section_id):
        return self.client.send_post('delete_section/' + str(section_id), {})

    def create_suite(self, name, description=None):
        return self.client.send_post('add_suite/' + str(self.project['id']),
                                     dict(name=name, description=description))

    def get_cases(self, suite_id, section_id=None):
        cases_uri = 'get_cases/{project_id}&suite_id={suite_id}'.format(
            project_id=self.project['id'],
            suite_id=suite_id
        )
        if section_id:
            cases_uri = '{0}&section_id={section_id}'.format(
                cases_uri, section_id=section_id
            )
        return self.client.send_get(cases_uri)

    def get_case(self, case_id):
        case_uri = 'get_case/{case_id}'.format(case_id=case_id)
        return self.client.send_get(case_uri)

    def get_case_by_name(self, suite_id, name, cases=None):
        for case in cases or self.get_cases(suite_id):
            if case['title'] == name:
                return self.get_case(case_id=case['id'])

    def get_case_by_group(self, suite_id, group, cases=None):
        for case in cases or self.get_cases(suite_id):
            if case['custom_test_group'] == group:
                return self.get_case(case_id=case['id'])

    def add_case(self, section_id, case):
        add_case_uri = 'add_case/{section_id}'.format(section_id=section_id)
        return self.client.send_post(add_case_uri, case)

    def delete_case(self, case_id):
        return self.client.send_post('delete_case/' + str(case_id), None)

    def get_case_fields(self):
        return self.client.send_get('get_case_fields')

    def get_plans(self, milestone_ids=None, limit=None):
        plans_uri = 'get_plans/{project_id}'.format(
            project_id=self.project['id'])
        if milestone_ids:
            plans_uri += '&milestone_id=' + ','.join([str(m)
                                                      for m in milestone_ids])
        if limit:
            plans_uri += '&limit={0}'.format(limit)
        return self.client.send_get(plans_uri)

    def get_plan(self, plan_id):
        plan_uri = 'get_plan/{plan_id}'.format(plan_id=plan_id)
        return self.client.send_get(plan_uri)

    def get_plan_by_name(self, name):
        for plan in self.get_plans():
            if plan['name'] == name:
                return self.get_plan(plan['id'])

    def add_plan(self, name, description, milestone_id, entries):
        add_plan_uri = 'add_plan/{project_id}'.format(
            project_id=self.project['id'])
        new_plan = {
            'name': name,
            'description': description,
            'milestone_id': milestone_id,
            'entries': entries
        }
        return self.client.send_post(add_plan_uri, new_plan)

    def update_plan(self, plan_id, name='', description='',
                    milestone_id=None, entries=None):
        if entries is None:
            entries = []
        update_plan_uri = 'update_plan/{plan_id}'.format(
            plan_id=plan_id)
        updated_plan = {}
        if name:
            updated_plan['name'] = name
        if description:
            updated_plan['description'] = description
        if milestone_id:
            updated_plan['milestone_id'] = milestone_id
        if entries:
            updated_plan['entries'] = entries
        return self.client.send_post(update_plan_uri, updated_plan)

    def add_plan_entry(self, plan_id, suite_id, config_ids, runs, name=None):
        add_plan_entry_uri = 'add_plan_entry/{plan_id}'.format(plan_id=plan_id)
        new_entry = {
            'suite_id': suite_id,
            'config_ids': config_ids,
            'runs': runs
        }
        if name:
            new_entry['name'] = name
        return self.client.send_post(add_plan_entry_uri, new_entry)

    def delete_plan(self, plan_id):
        delete_plan_uri = 'delete_plan/{plan_id}'.format(plan_id=plan_id)
        self.client.send_post(delete_plan_uri, {})

    def get_runs(self):
        runs_uri = 'get_runs/{project_id}'.format(
            project_id=self.project['id'])
        return self.client.send_get(uri=runs_uri)

    def get_run(self, run_id):
        run_uri = 'get_run/{run_id}'.format(run_id=run_id)
        return self.client.send_get(uri=run_uri)

    def get_run_by_name(self, name):
        for run in self.get_runs():
            if run['name'] == name:
                return self.get_run(run_id=run['id'])

    def get_previous_runs(self, milestone_id, suite_id, config_id, limit=None):
        all_runs = []
        for plan in self.get_plans(milestone_ids=[milestone_id], limit=limit):
            for entry in self.get_plan(plan['id'])['entries']:
                if entry['suite_id'] == suite_id:
                    run_ids = [run for run in entry['runs'] if
                               config_id in run['config_ids']]
                    all_runs.extend(run_ids)
        return all_runs

    def add_run(self, new_run):
        add_run_uri = 'add_run/{project_id}'.format(
            project_id=self.project['id'])
        return self.client.send_post(add_run_uri, new_run)

    def update_run(self, name, milestone_id=None, description=None,
                   config_ids=None, include_all=None, case_ids=None):
        tests_run = self.get_run(name)
        update_run_uri = 'update_run/{run_id}'.format(run_id=tests_run['id'])
        update_run = {}
        if milestone_id:
            update_run['milestone_id'] = milestone_id
        if description:
            update_run['description'] = description
        if include_all is not None:
            update_run['include_all'] = include_all is True
        if case_ids:
            update_run['case_ids'] = case_ids
        if config_ids:
            update_run['config_ids'] = config_ids
        return self.client.send_post(update_run_uri, update_run)

    def create_or_update_run(self, name, suite, milestone_id, description,
                             config_ids, include_all=True, assignedto=None,
                             case_ids=None):
        if self.get_run(name):
            self.update_run(name=name,
                            milestone_id=milestone_id,
                            description=description,
                            config_ids=config_ids,
                            include_all=include_all,
                            case_ids=case_ids)
        else:
            self.add_run(self.test_run_struct(name, suite, milestone_id,
                                              description, config_ids,
                                              include_all=include_all,
                                              assignedto=assignedto,
                                              case_ids=case_ids))

    def get_statuses(self):
        statuses_uri = 'get_statuses'
        return self.client.send_get(statuses_uri)

    def get_status(self, name):
        for status in self.get_statuses():
            if status['name'] == name:
                return status

    def get_tests(self, run_id, status_id=None):
        tests_uri = 'get_tests/{run_id}'.format(run_id=run_id)
        if status_id:
            tests_uri = '{0}&status_id={1}'.format(tests_uri,
                                                   ','.join(status_id))
        return self.client.send_get(tests_uri)

    def get_test(self, test_id):
        test_uri = 'get_test/{test_id}'.format(test_id=test_id)
        return self.client.send_get(test_uri)

    def get_test_by_name(self, run_id, name):
        for test in self.get_tests(run_id):
            if test['title'] == name:
                return self.get_test(test_id=test['id'])

    def get_test_by_group(self, run_id, group, tests=None):
        for test in tests or self.get_tests(run_id):
            if test['custom_test_group'] == group:
                return self.get_test(test_id=test['id'])

    def get_test_by_name_and_group(self, run_id, name, group):
        for test in self.get_tests(run_id):
            if test['title'] == name and test['custom_test_group'] == group:
                return self.get_test(test_id=test['id'])

    def get_tests_by_group(self, run_id, group, tests=None):
        test_list = []
        for test in tests or self.get_tests(run_id):
            if test['custom_test_group'] == group:
                test_list.append(self.get_test(test_id=test['id']))
        return test_list

    def get_results_for_test(self, test_id, run_results=None):
        if run_results:
            test_results = []
            for result in run_results:
                if result['test_id'] == test_id:
                    test_results.append(result)
            return test_results
        results_uri = 'get_results/{test_id}'.format(test_id=test_id)
        return self.client.send_get(results_uri)

    def get_results_for_run(self, run_id, created_after=None,
                            created_before=None, created_by=None, limit=None,
                            offset=None, status_id=None):
        results_run_uri = 'get_results_for_run/{run_id}'.format(run_id=run_id)
        if created_after:
            results_run_uri += '&created_after={}'.format(created_after)
        if created_before:
            results_run_uri += '&created_before={}'.format(created_before)
        if created_by:
            results_run_uri += '&created_by={}'.format(created_by)
        if limit:
            results_run_uri += '&limit={}'.format(limit)
        if offset:
            results_run_uri += '&offset={}'.format(offset)
        if status_id:
            results_run_uri += '&status_id={}'.format(status_id)
        return self.client.send_get(results_run_uri)

    def get_results_for_case(self, run_id, case_id):
        results_case_uri = 'get_results_for_case/{run_id}/{case_id}'.format(
            run_id=run_id, case_id=case_id)
        return self.client.send_get(results_case_uri)

    def get_all_results_for_case(self, run_ids, case_id):
        all_results = []
        for run_id in run_ids:
            try:
                results = self.get_results_for_case(run_id=run_id,
                                                    case_id=case_id)
            except APIError as e:
                logger.error("[{0}], run_id={1}, case_id={2}"
                             .format(e, run_id, case_id))
                continue
            all_results.extend(results)
        return all_results

    def add_results_for_test(self, test_id, test_results):
        new_results = {
            'status_id': self.get_status(test_results.status)['id'],
            'comment': '\n'.join(filter(lambda x: x is not None,
                                        [test_results.description,
                                         test_results.url,
                                         test_results.comments])),
            'elapsed': test_results.duration,
            'version': test_results.version
        }
        if test_results.steps:
            new_results['custom_step_results'] = test_results.steps
        return self.add_raw_results_for_test(test_id, new_results)

    def add_raw_results_for_test(self, test_id, test_raw_results):
        add_results_test_uri = 'add_result/{test_id}'.format(test_id=test_id)
        return self.client.send_post(add_results_test_uri, test_raw_results)

    def add_results_for_cases(self, run_id, suite_id, tests_results):
        add_results_test_uri = 'add_results_for_cases/{run_id}'.format(
            run_id=run_id)
        new_results = {'results': []}
        tests_cases = self.get_cases(suite_id)
        for results in tests_results:
            case = self.get_case_by_group(suite_id=suite_id,
                                          group=results.group,
                                          cases=tests_cases)
            case_id = case['id']
            new_result = {
                'case_id': case_id,
                'status_id': self.get_status(results.status)['id'],
                'comment': '\n'.join(filter(lambda x: x is not None,
                                            [results.description,
                                             results.url,
                                             results.comments])),
                'elapsed': results.duration,
                'version': results.version,
                'custom_launchpad_bug': results.launchpad_bug
            }
            if results.steps:
                custom_step_results = []
                steps = case.get('custom_test_case_steps', None)
                if steps and len(steps) == len(results.steps):
                    for s in zip(steps, results.steps):
                        custom_step_results.append({
                            "content": s[0]["content"],
                            "expected": s[0]["expected"],
                            "actual": s[1]['actual'],
                            "status_id": self.get_status(s[1]['status'])['id']
                        })
                else:
                    for s in results.steps:
                        custom_step_results.append({
                            "content": s['name'],
                            "expected": 'pass',
                            "actual": s['actual'],
                            "status_id": self.get_status(s['status'])['id']
                        })
                new_result['custom_test_case_steps_results'] = \
                    custom_step_results
            new_results['results'].append(new_result)
        return self.client.send_post(add_results_test_uri, new_results)

    def add_results_for_tempest_cases(self, run_id, tests_results):
        add_results_test_uri = 'add_results_for_cases/{run_id}'.format(
            run_id=run_id)
        new_results = {'results': tests_results}
        return self.client.send_post(add_results_test_uri, new_results)
