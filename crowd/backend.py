from suds.client import Client
import suds.xsd.doctor as dr
from django.contrib.auth.models import User, Group


class CrowdBackend:
    "Atlassian Crowd Authentication Backend"
    crowdClient = None
    authenticationToken = None
    principalToken = None

    NAME = "NAME"
    RANDOM_NUMBER = "Random-Number"
    REMOTE_ADDRESS = "remote_address"
    REMOTE_HOST = "remote_host"
    USER_AGENT = "User-Agent"
    X_FORWARDED_FOR = "X-Forwarded-For"


    def createClient(self):

    # The following dictionary has the targetNamespace as the key and a list
    # of namespaces that need to be imported as the value for that key
        patches = {"urn:SecurityServer": ["http://authentication.integration.crowd.atlassian.com",
                                          "http://soap.integration.crowd.atlassian.com",
                                          "http://exception.integration.crowd.atlassian.com",
                                          "http://rmi.java"],
                   "http://soap.integration.crowd.atlassian.com": ["urn:SecurityServer"]}

        # Create an ImportDoctor to use
        doctor = dr.ImportDoctor()

        # Patch all the imports into the proper targetNamespaces
        for targetNamespace in patches:
            for ns_import in patches[targetNamespace]:
                imp = dr.Import(ns_import)
                imp.filter.add(targetNamespace)
                doctor.add(imp)

            # Create the SOAP client, doctoring it to fix imports
        return Client(crowd_settings.AUTH_CROWD_SERVER_URI, doctor=doctor)

    def check_client_and_app_authentication(self):
        if (self.crowdClient is None):
            self.crowdClient = self.createClient()
        if (self.authenticationToken is None):
            self.authenticationToken = self.authenticateApplication(self.crowdClient)

    def create_or_update_user(self, user_id):
        self.check_client_and_app_authentication()

        user, created = User.objects.get_or_create(username=user_id)
        save_user = False
        if created:
        #logger.debug("Created Django user %s", username)
            user.set_unusable_password()
            save_user = True

        if( crowd_settings.AUTH_CROWD_ALWAYS_UPDATE_USER or created):
        #logger.debug("Populating Django user %s", username)
            self.populate_user(user)
            save_user = True

        if crowd_settings.AUTH_CROWD_MIRROR_GROUPS:
            self.populate_groups(user)
            save_user = True

        if save_user:
            user.save()

        return user


    def authenticate(self, username=None, password=None):
        self.check_client_and_app_authentication()
        self.principalToken = self.crowdClient.service.authenticatePrincipalSimple(self.authenticationToken, username,
                                                                                   password)
        return self.create_or_update_user(username)


    def get_user(self, user_id):
        user = None
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            pass

        return user


    def authenticateApplication(self, client):
        auth_context = client.factory.create('ns1:ApplicationAuthenticationContext')
        auth_context.name = crowd_settings.AUTH_CROWD_APPLICATION_USER
        auth_context.credential.credential = crowd_settings.AUTH_CROWD_APPLICATION_PASSWORD
        return client.service.authenticateApplication(auth_context)


    def populate_user(self, user):
        self.check_client_and_app_authentication()
        soap_principal = self.crowdClient.service.findPrincipalByName(self.authenticationToken, user.username)
        user.is_active = True
        for soapAttribute in soap_principal.attributes[0]:
            if (soapAttribute.name == "mail"):
                user.email = soapAttribute.values[0][0]
            if(soapAttribute.name == "givenName"):
                user.first_name = soapAttribute.values[0][0]
            if(soapAttribute.name == "sn"):
                user.last_name = soapAttribute.values[0][0]
        pass

    def populate_groups(self, user):
        self.check_client_and_app_authentication()
        arrayOfGroups = self.crowdClient.service.findGroupMemberships(self.authenticationToken, user.username)
        user.groups.clear()

        for crowdgroup in arrayOfGroups[0]:
            group, created = Group.objects.get_or_create(name=crowdgroup)
            if created:
                group.save()

            user.groups.add(group)
            if (group.name == crowd_settings.AUTH_CROWD_SUPERUSER_GROUP):
                user.is_superuser = True
            if (group.name == crowd_settings.AUTH_CROWD_STAFF_GROUP):
                user.is_staff = True

    def createValidationFactors(self, **kwargs):
        validatation_factors_list = list()
        for key in kwargs:
            myValidationFactor = self.crowdClient.factory.create("ns0:ValidationFactor")
            myValidationFactor.name = key
            myValidationFactor.value = kwargs[key]
            validatation_factors_list = validatation_factors_list, list(myValidationFactor)

        validation_factors = self.crowdClient.factory.create('ns0:ArrayOfValidationFactor')
        validation_factors.ValidationFactor = validatation_factors_list
        return validation_factors


    def findUserByToken(self, token, **kwargs):
        "returns the user if the principal token is valid"
        self.check_client_and_app_authentication()
        if self.crowdClient.service.isValidPrincipalToken(self.authenticationToken, token, self.createValidationFactors( **kwargs)):
            principal = self.crowdClient.service.findPrincipalByToken(
                    self.authenticationToken,
                    token)
            self.principalToken = token
            return self.create_or_update_user(principal.name)
        else:
            return None

    def getPrincipalToken(self, username, **kwargs):
        self.check_client_and_app_authentication()

        if self.principalToken is None:
            self.principalToken = self.crowdClient.service.createPrincipalToken(
                    self.authenticationToken,
                    username,
                    self.createValidationFactors(**kwargs))

        return self.principalToken


    def getCookieInfo(self):
        self.check_client_and_app_authentication()
        return self.crowdClient.service.getCookieInfo(self.authenticationToken)


class CrowdSettings(object):
    """
    This is a simple class to take the place of the global settings object. An
    instance will contain all of our settings as attributes, with default values
    if they are not specified by the configuration.
    """
    defaults = {
        'AUTH_CROWD_ALWAYS_UPDATE_USER': True,
        'AUTH_CROWD_MIRROR_GROUPS': True,
        'AUTH_CROWD_STAFF_GROUP': 'staff',
        'AUTH_CROWD_SUPERUSER_GROUP': 'superuser',
        'AUTH_CROWD_APPLICATION_USER': 'django',
        'AUTH_CROWD_APPLICATION_PASSWORD': 'django',
        'AUTH_CROWD_SERVER_URI': 'http://127.0.0.1:8095/crowd/services/SecurityServer?wsdl'
    }

    def __init__(self):
        """
        Loads our settings from django.conf.settings, applying defaults for any
        that are omitted.
        """
        from django.conf import settings

        for name, default in self.defaults.iteritems():
            value = getattr(settings, name, default)
            setattr(self, name, value)


        # Our global settings object

crowd_settings = CrowdSettings()
