#!/usr/bin/env python3
import argparse
import json
import os
import re
import botocore

from botocore.exceptions import ClientError


module_info = {
    # Name of the module (should be the same as the filename)
    'name': 'iam__enum_permissions',

    # Name and any other notes about the author
    'author': 'Spencer Gietzen of Rhino Security Labs',

    # Category of the module. Make sure the name matches an existing category.
    'category': 'ENUM',

    # One liner description of the module functionality.
    # This shows up when a user searches for modules.
    'one_liner': 'Tries to get a confirmed list of permissions for the current (or all) user(s).',

    # Description about what the module does and how it works
    'description': 'This module will attempt to use IAM APIs to enumerate a confirmed list of IAM permissions for the current user. This is done by checking attached and inline policies for the user and the groups they are in.',

    # A list of AWS services that the module utilizes during its execution
    'services': ['IAM'],

    # For prerequisite modules, try and see if any existing modules return the
    # data that is required for your module before writing that code yourself.
    # That way session data can stay separated and modular.
    'prerequisite_modules': ['iam__enum_users_roles_policies_groups'],

    # Module arguments to autocomplete when the user hits tab
    'arguments_to_autocomplete': ['--all-users', '--user-name']
}

parser = argparse.ArgumentParser(add_help=False, description=module_info['description'])

parser.add_argument('--all-users', required=False, default=False, action='store_true', help='Run this module against every user in the account and store the results to ./sessions/[current_session_name]/downloads/confirmed_permissions/[user_name].json. This data can then be run against the privesc_scan module with the --offline flag enabled.')
parser.add_argument('--user-name', required=False, default=None, help='A single username of a user to run this module against. By default, the user to which the active AWS keys belong to will be used.')
# parser.add_argument('--group-name', required=False, default=None, help='The name of a group to run this module against. By default, this module will be run against the user which the active AWS keys belong to.')
# parser.add_argument('--policy-name', required=False, default=None, help='The name of a specific policy to run this module against. By default, this module will be run against the user which the active AWS keys belong to.')


def main(args, pacu_main):
    session = pacu_main.get_active_session()

    ###### Don't modify these. They can be removed if you are not using the function.
    args = parser.parse_args(args)
    print = pacu_main.print
    input = pacu_main.input
    key_info = pacu_main.key_info
    fetch_data = pacu_main.fetch_data
    ######

    summary_data = {'users_confirmed': 0}

    users = []
    if args.all_users is True:
        if fetch_data(['IAM', 'Users'], module_info['prerequisite_modules'][0], '--users') is False:
            print('FAILURE')
            print('  SUB-MODULE EXECUTION FAILED')
            return
        fetched_users = session.IAM['Users']
        for user in fetched_users:
            users.append({
                'UserName': user['UserName'],
                'PermissionsConfirmed': True,
                'Permissions': {
                    'Allow': {},
                    'Deny': {}
                }
            })
    elif args.user_name is not None:
        users.append({
            'UserName': args.user_name,
            'PermissionsConfirmed': True,
            'Permissions': {
                'Allow': {},
                'Deny': {}
            }
        })
        summary_data['single_user'] = args.user_name
    else:
        client = pacu_main.get_boto3_client('sts')
        identity = client.get_caller_identity()
        active_aws_key = session.get_active_aws_key(pacu_main.database)

        if re.match(r'arn:aws:iam::\d{12}:user/', identity['Arn']) is not None:
            client = pacu_main.get_boto3_client('iam')
            try:
                user = client.get_user()
                active_aws_key.update(
                    pacu_main.database,
                    user_name=user['User']['UserName'],
                    user_arn=identity['Arn'],
                    user_id=identity['UserId'],
                    account_id=identity['Account']
                )
            except botocore.exceptions.ClientError:
                username = input('Failed to discover the current users username, enter it now or Ctrl+C to exit the module: ').strip()
                if username:
                    active_aws_key.update(
                        pacu_main.database,
                        user_name=username,
                        user_arn=identity['Arn'],
                        user_id=identity['UserId'],
                        account_id=identity['Account']
                    )
                else:
                    # Update the information from get_caller_identity and exit
                    active_aws_key.update(
                        pacu_main.database,
                        user_arn=identity['Arn'],
                        user_id=identity['UserId'],
                        account_id=identity['Account']
                    )
                    return False
        elif re.match(r'arn:aws:sts::\d{12}:assumed-role/', identity['Arn']) is not None:
            # TODO: Find role info
            active_aws_key.update(
                pacu_main.database,
                user_name=identity['User']['UserName'],
                user_arn=identity['Arn'],
                user_id=identity['UserId'],
                account_id=identity['Account']
            )
        else:
            print('Not an IAM user or role. Exiting...\n')
            return False
        user = key_info(alias=session.key_alias)
        user['PermissionsConfirmed'] = True
        user['Permissions'] = {'Allow': {}, 'Deny': {}}
        users.append(user)
        summary_data['single_user'] = user['UserName']

    # list-groups-for-user
    # list-user-policies
    # list-group-policies
    # list-role-policies
    # list-attached-role-policies
    # list-attached-group-policies
    # list-attached-user-policies
    # get-policy
    # get-policy-version
    # get-user-policy
    # get-group-policy
    # get-role-policy

    client = pacu_main.get_boto3_client('iam')

    print('Permission Document Location:')
    print('  sessions/{}/downloads/confirmed_permissions/'.format(session.name))
    print('Confirming Permissions for Users...')
    for user in users:
        print('  {}...'.format(user['UserName']))
        user['Groups'] = []
        user['Policies'] = []
        try:
            policies = []

            # Get groups that the user is in
            try:
                response = client.list_groups_for_user(
                    UserName=user['UserName']
                )
                user['Groups'] = response['Groups']
                while 'IsTruncated' in response and response['IsTruncated'] is True:
                    response = client.list_groups_for_user(
                        UserName=user['UserName'],
                        Marker=response['Marker']
                    )
                    user['Groups'] += response['Groups']
            except ClientError as error:
                print('    List groups for user failed')
                if error.response['Error']['Code'] == 'AccessDenied':
                    print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                else:
                    print('      {}'.format(error.response['Error']['Code']))
                user['PermissionsConfirmed'] = False

            # Get inline and attached group policies
            for group in user['Groups']:
                group['Policies'] = []
                # Get inline group policies
                try:
                    response = client.list_group_policies(
                        GroupName=group['GroupName']
                    )
                    policies = response['PolicyNames']
                    while 'IsTruncated' in response and response['IsTruncated'] is True:
                        response = client.list_group_policies(
                            GroupName=group['GroupName'],
                            Marker=response['Marker']
                        )
                        policies += response['PolicyNames']
                except ClientError as error:
                    print('     List group policies failed')
                    if error.response['Error']['Code'] == 'AccessDenied':
                        print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                    else:
                        print('      {}'.format(error.response['Error']['Code']))
                    user['PermissionsConfirmed'] = False

                # Get document for each inline policy
                for policy in policies:
                    group['Policies'].append({  # Add policies to list of policies for this group
                        'PolicyName': policy
                    })
                    try:
                        document = client.get_group_policy(
                            GroupName=group['GroupName'],
                            PolicyName=policy
                        )['PolicyDocument']
                    except ClientError as error:
                        print('     Get group policy failed')
                        if error.response['Error']['Code'] == 'AccessDenied':
                            print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                        else:
                            print('      {}'.format(error.response['Error']['Code']))
                        user['PermissionsConfirmed'] = False
                    user = parse_document(document, user)

                # Get attached group policies
                attached_policies = []
                try:
                    response = client.list_attached_group_policies(
                        GroupName=group['GroupName']
                    )
                    attached_policies = response['AttachedPolicies']
                    while 'IsTruncated' in response and response['IsTruncated'] is True:
                        response = client.list_attached_group_policies(
                            GroupName=group['GroupName'],
                            Marker=response['Marker']
                        )
                        attached_policies += response['AttachedPolicies']
                    group['Policies'] += attached_policies
                except ClientError as error:
                    print('    List attached group policies failed')
                    if error.response['Error']['Code'] == 'AccessDenied':
                        print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                    else:
                        print('      {}'.format(error.response['Error']['Code']))
                    user['PermissionsConfirmed'] = False
                user = parse_attached_policies(client, attached_policies, user)

            # Get inline user policies
            policies = []
            if 'Policies' not in user:
                user['Policies'] = []
            try:
                response = client.list_user_policies(
                    UserName=user['UserName']
                )
                policies = response['PolicyNames']
                while 'IsTruncated' in response and response['IsTruncated'] is True:
                    response = client.list_user_policies(
                        UserName=user['UserName'],
                        Marker=response['Marker']
                    )
                    policies += response['PolicyNames']
                for policy in policies:
                    user['Policies'].append({
                        'PolicyName': policy
                    })
            except ClientError as error:
                print('    List user policies failed')
                if error.response['Error']['Code'] == 'AccessDenied':
                    print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                else:
                    print('      {}'.format(error.response['Error']['Code']))
                user['PermissionsConfirmed'] = False

            # Get document for each inline policy
            for policy in policies:
                try:
                    document = client.get_user_policy(
                        UserName=user['UserName'],
                        PolicyName=policy
                    )['PolicyDocument']
                except ClientError as error:
                    print('    Get user policy failed')
                    if error.response['Error']['Code'] == 'AccessDenied':
                        print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                    else:
                        print('      {}'.format(error.response['Error']['Code']))
                    user['PermissionsConfirmed'] = False
                user = parse_document(document, user)

            # Get attached user policies
            attached_policies = []
            try:
                response = client.list_attached_user_policies(
                    UserName=user['UserName']
                )
                attached_policies = response['AttachedPolicies']
                while 'IsTruncated' in response and response['IsTruncated'] is True:
                    response = client.list_attached_user_policies(
                        UserName=user['UserName'],
                        Marker=response['Marker']
                    )
                    attached_policies += response['AttachedPolicies']
                user['Policies'] += attached_policies
            except ClientError as error:
                print('    List attached user policies failed')
                if error.response['Error']['Code'] == 'AccessDenied':
                    print('      FAILURE: MISSING REQUIRED AWS PERMISSIONS')
                else:
                    print('      {}'.format(error.response['Error']['Code']))
                user['PermissionsConfirmed'] = False

            user = parse_attached_policies(client, attached_policies, user)
            if user['PermissionsConfirmed']:
                summary_data['users_confirmed'] += 1

            if args.user_name is None and args.all_users is False:
                print('  Confirmed Permissions for {}'.format(user['UserName']))
                active_aws_key.update(
                    pacu_main.database,
                    user_name=user['UserName'],
                    user_arn=user['UserArn'],
                    user_id=user['UserId'],
                    groups=user['Groups'],
                    policies=user['Policies'],
                    permissions_confirmed=user['PermissionsConfirmed'],
                    allow_permissions=user['Permissions']['Allow'],
                    deny_permissions=user['Permissions']['Deny']
                )
            else:
                if not os.path.exists('sessions/{}/downloads/confirmed_permissions/'.format(session.name)):
                    os.makedirs('sessions/{}/downloads/confirmed_permissions/'.format(session.name))

                with open('sessions/{}/downloads/confirmed_permissions/{}.json'.format(session.name, user['UserName']), 'w+') as user_permissions_file:
                    json.dump(user, user_permissions_file, indent=2, default=str)

                print('    {}\'s permissions stored in {}.json'.format(user['UserName'], user['UserName']))
        except ClientError as error:
            if error.response['Error']['Code'] == 'AccessDenied':
                print('  FAILURE: MISSING REQUIRED AWS PERMISSIONS')
            else:
                print('  {}'.format(error.response['Error']['Code']))
            print('Skipping {}'.format(user['UserName'], error))

    print('\n{} completed.\n'.format(module_info['name']))
    return summary_data


def summary(data, pacu_main):
    out = ''
    if data['users_confirmed'] == 1:
        out += '  Confirmed Permissions for: {}.\n'.format(data['single_user'])
    else:
        out += '  Confirmed Permissions for {} User(s).\n'.format(data['users_confirmed'])
    return out


def parse_attached_policies(client, attached_policies, user):
    """ Pull permissions from each policy document. """
    for policy in attached_policies:
        document = get_attached_policy(client, policy['PolicyArn'])
        if document is False:
            user['PermissionsConfirmed'] = False
        else:
            user = parse_document(document, user)
    return user


def get_attached_policy(client, policy_arn):
    """ Get the policy document of an attached policy. """
    try:
        policy = client.get_policy(
            PolicyArn=policy_arn
        )['Policy']
        version = policy['DefaultVersionId']
        can_get = True
    except Exception as error:
        print('Get policy failed: {}'.format(error))
        return False

        # NOTE: If v1, v2, and v3 exist, then v2 is deleted, the next version will be v4 still, so this WILL error currently
        # print('Attempting to enumerate the default version...')
        # can_get = False

    try:
        if can_get is True:
            document = client.get_policy_version(
                PolicyArn=policy_arn,
                VersionId=version
            )['PolicyVersion']['Document']
            return document

        # else:  # If the user can't run get_policy, try to run get_policy_version to enumerate the default version
        #     for version in ['v1', 'v2', 'v3', 'v4', 'v5']:  # This won't error because it will return the default version before fetching a non-existent version
        #         policy_version = client.get_policy_version(
        #             PolicyArn=policy_arn,
        #             VersionId=version
        #         )['PolicyVersion']
        #         if policy_version['IsDefaultVersion'] is True:
        #             return policy_version['Document']

    except Exception as error:
        print('Get policy version failed: {}'.format(error))
        return False


def parse_document(document, user):
    """ Loop permissions, resources, and conditions """
    if isinstance(document['Statement'], dict):
        document['Statement'] = [document['Statement']]

    for statement in document['Statement']:

        if statement['Effect'] == 'Allow':

            if 'Action' in statement and isinstance(statement['Action'], list):  # Check if the action is a single action (str) or multiple (list)
                statement['Action'] = list(set(statement['Action']))  # Remove duplicates to stop the circular reference JSON error
                for action in statement['Action']:
                    if action in user['Permissions']['Allow']:
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Allow'][action]['Resources'] += statement['Resource']
                        else:
                            user['Permissions']['Allow'][action]['Resources'].append(statement['Resource'])
                    else:
                        user['Permissions']['Allow'][action] = {'Resources': [], 'Conditions': []}
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Allow'][action]['Resources'] = statement['Resource']
                        else:
                            user['Permissions']['Allow'][action]['Resources'] = [statement['Resource']]
                    if 'Condition' in statement:
                            user['Permissions']['Allow'][action]['Conditions'].append(statement['Condition'])
                    user['Permissions']['Allow'][action]['Resources'] = list(set(user['Permissions']['Allow'][action]['Resources']))  # Remove duplicate resources

            elif 'Action' in statement and isinstance(statement['Action'], str):
                if statement['Action'] in user['Permissions']['Allow']:
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Allow'][statement['Action']]['Resources'] += statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['Action']]['Resources'].append(statement['Resource'])
                else:
                    user['Permissions']['Allow'][statement['Action']] = {'Resources': [], 'Conditions': []}
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Allow'][statement['Action']]['Resources'] = statement['Resource']
                    else:
                        user['Permissions']['Allow'][statement['Action']]['Resources'] = [statement['Resource']]  # Make sure that resources are always arrays
                if 'Condition' in statement:
                    user['Permissions']['Allow'][statement['Action']]['Conditions'].append(statement['Condition'])
                user['Permissions']['Allow'][statement['Action']]['Resources'] = list(set(user['Permissions']['Allow'][statement['Action']]['Resources']))  # Remove duplicate resources

            if 'NotAction' in statement and isinstance(statement['NotAction'], list):  # NotAction is reverse, so allowing a NotAction is denying that action basically
                statement['NotAction'] = list(set(statement['NotAction']))  # Remove duplicates to stop the circular reference JSON error
                for not_action in statement['NotAction']:
                    if '!{}'.format(not_action) in user['Permissions']['Allow']:
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Allow']['!{}'.format(not_action)]['Resources'] += statement['Resource']
                        else:
                            user['Permissions']['Allow']['!{}'.format(not_action)]['Resources'].append(statement['Resource'])
                    else:
                        user['Permissions']['Allow']['!{}'.format(not_action)] = {'Resources': [], 'Conditions': []}
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Allow']['!{}'.format(not_action)]['Resources'] = statement['Resource']
                        else:
                            user['Permissions']['Allow']['!{}'.format(not_action)]['Resources'] = [statement['Resource']]
                    if 'Condition' in statement:
                        user['Permissions']['Allow']['!{}'.format(not_action)]['Conditions'].append(statement['Condition'])
                    user['Permissions']['Allow']['!{}'.format(not_action)]['Resources'] = list(set(user['Permissions']['Allow']['!{}'.format(not_action)]['Resources']))  # Remove duplicate resources

            elif 'NotAction' in statement and isinstance(statement['NotAction'], str):
                if '!{}'.format(statement['NotAction']) in user['Permissions']['Allow']:
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources'] += statement['Resource']
                    else:
                        user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources'].append(statement['Resource'])
                else:
                    user['Permissions']['Allow']['!{}'.format(statement['NotAction'])] = {'Resources': [], 'Conditions': []}
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources'] = statement['Resource']
                    else:
                        user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources'] = [statement['Resource']]  # Make sure that resources are always arrays
                if 'Condition' in statement:
                    user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Conditions'].append(statement['Condition'])
                user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources'] = list(set(user['Permissions']['Allow']['!{}'.format(statement['NotAction'])]['Resources']))  # Remove duplicate resources

        if statement['Effect'] == 'Deny':

            if 'Action' in statement and isinstance(statement['Action'], list):
                statement['Action'] = list(set(statement['Action']))  # Remove duplicates to stop the circular reference JSON error
                for action in statement['Action']:
                    if action in user['Permissions']['Deny']:
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Deny'][action]['Resources'] += statement['Resource']
                        else:
                            user['Permissions']['Deny'][action]['Resources'].append(statement['Resource'])
                    else:
                        user['Permissions']['Deny'][action] = {'Resources': [], 'Conditions': []}
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Deny'][action]['Resources'] = statement['Resource']
                        else:
                            user['Permissions']['Deny'][action]['Resources'] = [statement['Resource']]
                    if 'Condition' in statement:
                        user['Permissions']['Deny'][action]['Conditions'].append(statement['Condition'])
                    user['Permissions']['Deny'][action]['Resources'] = list(set(user['Permissions']['Deny'][action]['Resources']))  # Remove duplicate resources

            elif 'Action' in statement and isinstance(statement['Action'], str):
                if statement['Action'] in user['Permissions']['Deny']:
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Deny'][statement['Action']]['Resources'] += statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['Action']]['Resources'].append(statement['Resource'])
                else:
                    user['Permissions']['Deny'][statement['Action']] = {'Resources': [], 'Conditions': []}
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Deny'][statement['Action']]['Resources'] = statement['Resource']
                    else:
                        user['Permissions']['Deny'][statement['Action']]['Resources'] = [statement['Resource']]  # Make sure that resources are always arrays
                if 'Condition' in statement:
                    user['Permissions']['Deny'][statement['Action']]['Conditions'].append(statement['Condition'])
                user['Permissions']['Deny'][statement['Action']]['Resources'] = list(set(user['Permissions']['Deny'][statement['Action']]['Resources']))  # Remove duplicate resources

            if 'NotAction' in statement and isinstance(statement['NotAction'], list):  # NotAction is reverse, so allowing a NotAction is denying that action basically
                statement['NotAction'] = list(set(statement['NotAction']))  # Remove duplicates to stop the circular reference JSON error
                for not_action in statement['NotAction']:
                    if '!{}'.format(not_action) in user['Permissions']['Deny']:
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Deny']['!{}'.format(not_action)]['Resources'] += statement['Resource']
                        else:
                            user['Permissions']['Deny']['!{}'.format(not_action)]['Resources'].append(statement['Resource'])
                    else:
                        user['Permissions']['Deny']['!{}'.format(not_action)] = {'Resources': [], 'Conditions': []}
                        if isinstance(statement['Resource'], list):
                            user['Permissions']['Deny']['!{}'.format(not_action)]['Resources'] = statement['Resource']
                        else:
                            user['Permissions']['Deny']['!{}'.format(not_action)]['Resources'] = [statement['Resource']]
                    if 'Condition' in statement:
                        user['Permissions']['Deny']['!{}'.format(not_action)]['Conditions'].append(statement['Condition'])
                    user['Permissions']['Deny']['!{}'.format(not_action)]['Resources'] = list(set(user['Permissions']['Deny']['!{}'.format(not_action)]['Resources']))  # Remove duplicate resources

            elif 'NotAction' in statement and isinstance(statement['NotAction'], str):
                if '!{}'.format(statement['NotAction']) in user['Permissions']['Deny']:
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources'] += statement['Resource']
                    else:
                        user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources'].append(statement['Resource'])
                else:
                    user['Permissions']['Deny']['!{}'.format(statement['NotAction'])] = {'Resources': [], 'Conditions': []}
                    if isinstance(statement['Resource'], list):
                        user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources'] = statement['Resource']
                    else:
                        user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources'] = [statement['Resource']]  # Make sure that resources are always arrays
                if 'Condition' in statement:
                    user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Conditions'].append(statement['Condition'])
                user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources'] = list(set(user['Permissions']['Deny']['!{}'.format(statement['NotAction'])]['Resources']))  # Remove duplicate resources

    return user
