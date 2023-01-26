class AliasExistsException(Exception):
    pass

class CodeMismatchException(Exception):
    pass

class ExpiredCodeException(Exception):
    pass

class InvalidParameterException(Exception):
    pass

class LimitExceededException(Exception):
    pass

class NewPasswordRequiredError(Exception):
    pass

class NotAuthorizedException(Exception):
    pass

class ParamValidationError(Exception):
    pass

class PasswordResetRequiredException(Exception):
    pass

class UserNotConfirmedException(Exception):
    pass

class UserNotFoundException(Exception):
    pass

class UsernameExistsException(Exception):
    pass