questLog REST API
=================

.. toctree::
   :maxdepth: 2
   :caption: Contents:


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

Resources
---------
The questLog REST API is based around four types of resources,

* Users (canonically "user")
* To-Dos (canonically "todo")
* Projcts (canonically "project")
* Challenges (canonically "challenge")

The fourth resource type handles user authentication, through a challenge-solution mechanism.

Use route,

.. code-block ::

   /api/<type>/<name>

Where type is the resource type (see canonical names above), and the name is the unique name of the resource.

For all routes,

* If the request is missing key-pair arguments, HTTP code 422 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Request missing arguments."
    }

* If the request has key-pair arguments of the incorrect value type, HTTP code 422 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Invalid request argument types."
    }

* If a method is used outside of accepted methods, HTTP code 405 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Method not allowed."
    }

* If the name does not exist in type's database collection, and the method is not PUT, HTTP code 404 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Resource does not exist."
    }

* If the name does exist in database collection, and the method is PUT, HTTP code 409 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Resource already exists."
    }

* If the "solution" key-pair argument is incorrect, or if the submitted "author" key-pair argument is invalid, HTTP code 401 is returned, with the following JSON data:

.. code-block :: json

    {
       "error": "Unauthorized."
    }

* If the method is PUT, and all arguments were valid, HTTP code 201 is returned, with no JSON data.
* If the method is PATCH or DELETE, and all arguments were valid, HTTP code 204 is returned, with no JSON data.

* If key-pair for "author" or "contributor" does not exist in user collection, HTTP code 422 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "Resource linkage to user does not exist."
    }

Authentication & Challenges
---------------------------
Route:

.. code-block ::

   /api/challenge/<name>

* Accepted methods: GET
* Name must exist in user collection.
* If the name does exist, HTTP code 200 is returned, with the following JSON data:

.. code-block :: json

    {
       "challenge": "",
       "session": "",
       "expiry": "",
       "nonce": "",
       "tag": "",
    }

...Where,

* challenge is the encrypted string, that when decrypted, returns a "truth" string,
* session is the encrypted AES session key, which after decryption is to be used to further decrypt the challenge string,
* expiry is the UNIX timestamp notating when the challenge is expired, and is no longer valid,
* nonce is the cryptographic nonce,
* tag is the message authentication code, which ensures data integrity.

The key-value pairs above are in hexadecimal form. Please convert them back into bytes upon receiving the JSON data.

Challenges are responsible for user authentication.

When sending requests that require user authentication, any applications interfacing with the API must include a key-value pair called "solution" which associates to a random string of text.
This solution string is to be treated like a temporary password for its associated user, of which the request is being performed on behalf of.
The ephemeral nature of the solution string means it will expire. The lifespan of the solution string is dictated by the "main.cfg" configuration file (see comments in file for specific field). The default is 900 seconds.
Upon expiration, the accepted solution string will change. Any requests made with previous solution strings will be rejected.
By default, the solution string represented in byte-form (canonically, it's in hexadecimal form for encoding reasons) is 2048 bytes long. This is also configurable through the "main.cfg" configuration file.

To acquire a solution for a user, an application must first be in possession of the user's RSA private key.
Assuming this condition is met, the application then is to request the user challenge, with the key-value pairs shown above.
Then, it should decrypt the AES session key using the RSA private key with PCKS#1 OAEP.
The final solution string is to be decrypted using the newly obtained AES session key, plugging in the nonce and tag into the decryption function.

Again, the solution string will expire, and upon expiration, the challenge will be regenerated.
It's recommended to check a cached challenge's expiry timestamp, and if the timestamp stated has past, repeat operations required to procure a new solution string.

Users
-----
Route:

.. code-block ::

   /api/user/<name>

* Accepted methods: PUT, PATCH, DELETE, GET
* For PUT requests, name must not exist in user collection.
* For PATCH, DELETE, and GET requests, name must exist in user collection.
* If the name does exist, and the method is GET, HTTP code 200 is returned, with the following JSON data:

.. code-block :: json

    {
       "key": "",
       "email": "",
       "name": ""
    }

...Where,

* key is the RSA public key for authenticating requests made upon behalf of this user,
* email is an email address belonging to the user,
* name being the unique name of the user.

Methods PATCH and DELETE require authentication. Please include a "solution" argument to your requests.

PUT requests require arguments "key" and "email".

PATCH requests will overwrite key-pairs on database with those defined in the request.
Please exert caution when overwriting the field for the user's public RSA key.
There is no method of recovering an account if the key is overwritten with an invalid value.
Moreover, overwiting the key may result in solution submissions being rejected, as the challenge string may have not expired recently, to qualify for re-generation with the new key.
PATCH requests cannot overwrite the name field.

Users are the basic actors that operate projects and to-dos.

To-dos
------
Route:

.. code-block ::

    /api/todo/<name>

* Accepted methods: PUT, PATCH, DELETE, GET
* For PUT requests, name must not exist in to-do collection.
* For PATCH, DELETE, and GET requests, name must exist in to-do collection.
* If name does exist, and the method is GET, HTTP code 200 is returned, with the following JSON data:

.. code-block :: json

    {
        "startTime": 0,
        "endTime": 0,
        "status": "init",
        "description": "",
        "requires": [],
        "hubs": {},
        "author": "",
        "projects": [],
        "name": ""
    }

...Where,

* startTime is the time when the to-do was opened, expressed in UNIX time as an integer,
* endTime is the time when the to-do was closed, expressed in UNIX time as an integer, if still open leave as null,
* status is the current to-do status (accepted statuses are, "init", "dropped", "wip", "complete"),
* description is the description of the to-do,
* requires is a list of names required for the to-do, it is not checked by the API for validity,
* hubs is a dictionary of key-pairs for relevant links to the to-do (i.e a Git issue) with keys being the name of the link, and values the actual link,
* author is the creator of the to-do,
* projects is a list of names of projects the to-do is associated with, it is checked by the API for validity and authentication (whether the author of the to-do has relevant permissions to link the to-do),
* name is the name of the to-do.

Methods PATCH and DELETE require authentication. Please include a "solution" argument to your requests.

PUT, PATCH, and DELETE requests require arguments "author" (or "contributor") and "solution".

PATCH requests will overwrite key-pairs on database with those defined in the request.
PATCH requests cannot overwrite the author field.
PATCH requests cannot overwrite the name field.

To-dos are resources designed for tracking specific tasks through their lifecycle.

Projects
--------
Route:

.. code-block ::

    /api/project/<name>

* Accepted methods: PUT, PATCH, DELETE, GET, POST
* For PUT requests, name must not exist in project collection.
* For PATCH, DELETE, GET, and POST requests, name must exist in project collection.
* If name does exist, and the method is GET, HTTP code 200 is returned, with the following JSON data:

.. code-block :: json

    {
        "startTime": 0,
        "endTime": 0,
        "status": "init",
        "description": "",
        "requires": [],
        "hubs": {},
        "author": "",
        "contributors": [],
        "invitations": [],
        "name": ""
    }

...Where,

* startTime is the time when the project was started, expressed in UNIX time as an integer,
* endTime is the time when the project was ended or completed, expressed in UNIX time as an integer, if still in development leave as null,
* status is the current project status (accepted statuses are, "init", "dropped", "wip", "complete", "maintenance", "active"),
* description is the description of the project,
* requires is a list of names required for the project, it is not checked by the API for validity,
* hubs is a dictionary of key-pairs for relevant links to the project (i.e a project discussion channel) with keys being the name of the link, and values the actual link,
* author is the creator of the project,
* contributors is a list of names of users who are contributing to the project, and have edit access over the project resource,
* invitations is a list of names of users who are invited by the author to be contributors,
* name is the name of the project.

* If name does exist, and the method is PATCH, PUT, or DELETE, with arguments for key-pairs "contributors" and "invitations", HTTP code 422 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "Contributors and invitations cannot be modified through PATCH, PUT, or DELETE."
    }

* If a request attempts to authenticate as both author and contributor, HTTP code 422 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "Cannot authenticate as both author and contributor."
    }

Methods PATCH, DELETE, and POST require authentication. Please include a "solution" argument to your requests.
Only the author can use the DELETE method.
Attempting to perform a PUT request while authenticating as a contributor will result in "request missing arguments."

PATCH requests will overwrite key-pairs on database with those defined in the request.
PATCH requests cannot overwrite the author field.
PATCH requests also cannot directly overwrite the "contributors" and "invitations" list. Use POST method instead.
PATCH requests cannot overwrite the name field.

PUT and PATCH requests require arguments "author" and "solution".

POST requests are for authors to add or remove users from the invitations list, and for users to accept invitations into the contributors list.
To add users to the invitations list, use arguments "contributor" for the name of the to-be-invited user, and "author" and "solution" for authentication, without specifying key "cancel" or "remove".
Specify key "cancel" to cancel an invitation, specify key "remove" to remove a contributor.
To accept an invitation, use arguments "contributor" and "solution" without specifiying key "decline" and "author".
Specify key "decline" to remove oneself from the invitations list, without joining contributors list.

* If a POST request made on behalf of the author attempts to remove a contributor who isn't in the contributors list, HTTP code 404 is returned, with the following jSON data:

.. code-block :: json

    {
        "error": "User not in contributors."
    }

* If a POST request made on behalf of the author attempts to cancel an invitation that does not exist, HTTP code 404 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "Invitation does not exist."
    }

* If a POST request made on behalf of a contributor attempts to decline an invitation that does not exist, HTTP code 404 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "User not in invitations."
    }

Projects are resources designed for tracking larger tasks and operations, with many children to-do resources.

Index
-----
Route:

.. code-block ::

   /api/<resource>

* Accepted methods: GET
* If the resource type exists and the method is GET, HTTP code 200 is returned, with the following JSON data:

.. code-block :: json

    {
        "resource": "",
        "items": []
    }

...Where,
* resource is the name of the resource type (user, todo, or project),
* items is a list of all names in the specified collection.

* If the resource type does not exist and the method is GET, HTTP code 404 is returned, with the following JSON data:

.. code-block :: json

    {
        "error": "Resource type unknown."
    }

The index URI is designed for listing all resources in a given collection.
