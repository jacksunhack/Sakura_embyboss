# -*- coding: utf-8 -*-
"""
SQLAlchemy models and helper functions for managing user invitations.
"""
import asyncio # Added for asyncio.to_thread
from sqlalchemy import Column, BigInteger, String, DateTime, Integer, func, UniqueConstraint
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from bot import LOGGER
from bot.sql_helper import Base, Session, engine

# --- SQLAlchemy Model Definition ---
class InvitationLog(Base):
    """
    Represents an invitation log in the database.
    """
    __tablename__ = 'invitation_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    invitation_code = Column(String(50), unique=True, index=True, nullable=False)
    inviter_user_id = Column(BigInteger, nullable=False) # Telegram ID of the inviter
    invited_user_id = Column(BigInteger, nullable=True)  # Telegram ID of the user who used the code
    status = Column(String(20), default='pending', nullable=False)  # e.g., 'pending', 'completed', 'expired'
    creation_timestamp = Column(DateTime, default=func.now(), nullable=False)
    completion_timestamp = Column(DateTime, nullable=True)

    # For ensuring inviter_user_id + invitation_code is unique if needed,
    # but invitation_code itself is already unique.
    # __table_args__ = (UniqueConstraint('inviter_user_id', 'invitation_code', name='_inviter_code_uc'),)

    def __repr__(self):
        return (f"<InvitationLog(id={self.id}, code='{self.invitation_code}', "
                f"inviter='{self.inviter_user_id}', invited='{self.invited_user_id}', "
                f"status='{self.status}')>")

# --- Create Table ---
# This ensures the table is created in the database if it doesn't exist.
InvitationLog.__table__.create(bind=engine, checkfirst=True)
LOGGER.info("SQLAlchemy: 'invitation_log' table checked/created.")


# --- Helper Functions ---

# Wrapper for running synchronous SQLAlchemy calls in a separate thread
async def run_sync_db_call(func_to_run, *args, **kwargs):
    """
    Runs a synchronous function (like SQLAlchemy operations) in a separate thread
    to avoid blocking the asyncio event loop.
    """
    try:
        # For Python 3.9+
        return await asyncio.to_thread(func_to_run, *args, **kwargs)
    except AttributeError:
        # Fallback for Python < 3.9 (less common now, but good for wider compatibility if needed)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func_to_run(*args, **kwargs))


def _sync_sql_add_invitation(invitation_code: str, inviter_user_id: int) -> bool:
    """
    Adds a new invitation to the log.

    :param invitation_code: The unique invitation code.
    :param inviter_user_id: The Telegram ID of the user who created the invitation.
    :return: True if the invitation was added successfully, False otherwise.
    """
    # This is the original synchronous logic
    session = Session()
    try:
        new_invitation = InvitationLog(
            invitation_code=invitation_code,
            inviter_user_id=inviter_user_id,
            status='pending'
        )
        session.add(new_invitation)
        session.commit()
        LOGGER.info(f"Invitation added: Code '{invitation_code}', Inviter ID '{inviter_user_id}'.")
        return True
    except IntegrityError:
        session.rollback()
        LOGGER.warning(f"Failed to add invitation: Code '{invitation_code}' already exists.")
        return False
    except SQLAlchemyError as e:
        session.rollback()
        LOGGER.error(f"Database error while adding invitation '{invitation_code}': {e}", exc_info=True)
        return False
    finally:
        session.close()

async def sql_add_invitation(invitation_code: str, inviter_user_id: int) -> bool:
    """
    Asynchronously adds a new invitation to the log.
    """
    return await run_sync_db_call(_sync_sql_add_invitation, invitation_code, inviter_user_id)


def _sync_sql_get_invitation_by_code(code: str) -> InvitationLog | None:
    # This is the original synchronous logic
    """
    Retrieves an invitation by its code.

    :param code: The invitation code to search for.
    :return: An InvitationLog object if found, None otherwise.
    """
    session = Session()
    try:
        invitation = session.query(InvitationLog).filter(InvitationLog.invitation_code == code).first()
        return invitation
    except SQLAlchemyError as e:
        LOGGER.error(f"Database error while retrieving invitation by code '{code}': {e}", exc_info=True)
        return None
    finally:
        session.close()

async def sql_get_invitation_by_code(code: str) -> InvitationLog | None:
    """
    Asynchronously retrieves an invitation by its code.
    """
    return await run_sync_db_call(_sync_sql_get_invitation_by_code, code)


def _sync_sql_mark_invitation_completed(invitation_code: str, invited_user_id: int) -> bool:
    # This is the original synchronous logic
    """
    Marks an invitation as completed.

    :param invitation_code: The invitation code to update.
    :param invited_user_id: The Telegram ID of the user who completed the invitation.
    :return: True if the update was successful, False otherwise.
    """
    session = Session()
    try:
        invitation = session.query(InvitationLog).filter(InvitationLog.invitation_code == invitation_code).first()
        if invitation:
            if invitation.status == 'pending':
                invitation.status = 'completed'
                invitation.invited_user_id = invited_user_id
                invitation.completion_timestamp = func.now()
                session.commit()
                LOGGER.info(f"Invitation '{invitation_code}' marked as completed by User ID '{invited_user_id}'.")
                return True
            else:
                LOGGER.warning(f"Invitation '{invitation_code}' is not pending (status: {invitation.status}). Cannot mark as completed.")
                session.rollback()
                return False
        else:
            LOGGER.warning(f"Invitation '{invitation_code}' not found. Cannot mark as completed.")
            return False
    except SQLAlchemyError as e:
        session.rollback()
        LOGGER.error(f"Database error while marking invitation '{invitation_code}' completed: {e}", exc_info=True)
        return False
    finally:
        session.close()

async def sql_mark_invitation_completed(invitation_code: str, invited_user_id: int) -> bool:
    """
    Asynchronously marks an invitation as completed.
    """
    return await run_sync_db_call(_sync_sql_mark_invitation_completed, invitation_code, invited_user_id)


def _sync_sql_get_successful_invites_count(inviter_user_id: int) -> int:
    # This is the original synchronous logic
    """
    Counts the number of successfully completed invitations for a given inviter.

    :param inviter_user_id: The Telegram ID of the inviter.
    :return: The count of completed invitations.
    """
    session = Session()
    try:
        count = session.query(func.count(InvitationLog.id)).filter(
            InvitationLog.inviter_user_id == inviter_user_id,
            InvitationLog.status == 'completed'
        ).scalar()
        return count if count is not None else 0
    except SQLAlchemyError as e:
        LOGGER.error(f"Database error while counting successful invites for User ID '{inviter_user_id}': {e}", exc_info=True)
        return 0
    finally:
        session.close()

async def sql_get_successful_invites_count(inviter_user_id: int) -> int:
    """
    Asynchronously counts the number of successfully completed invitations for a given inviter.
    """
    return await run_sync_db_call(_sync_sql_get_successful_invites_count, inviter_user_id)


def _sync_sql_invitation_code_exists(invitation_code: str) -> bool:
    # This is the original synchronous logic
    """
    Checks if a given invitation code already exists.

    :param invitation_code: The invitation code to check.
    :return: True if the code exists, False otherwise.
    """
    session = Session()
    try:
        exists = session.query(InvitationLog.id).filter(InvitationLog.invitation_code == invitation_code).first() is not None
        return exists
    except SQLAlchemyError as e:
        LOGGER.error(f"Database error while checking existence of invitation code '{invitation_code}': {e}", exc_info=True)
        return False
    finally:
        session.close()

async def sql_invitation_code_exists(invitation_code: str) -> bool:
    """
    Asynchronously checks if a given invitation code already exists.
    """
    return await run_sync_db_call(_sync_sql_invitation_code_exists, invitation_code)


# --- Example Usage (Updated for async) ---
async def _main_async_test():
    LOGGER.info("Running ASYNC example usage for sql_invitations...")

    test_code_1 = "ASYNCTEST123"
    test_inviter_1 = 100000001
    if not await sql_invitation_code_exists(test_code_1):
        if await sql_add_invitation(test_code_1, test_inviter_1):
            LOGGER.info(f"Successfully added async test invitation: {test_code_1}")
        else:
            LOGGER.error(f"Failed to add async test invitation: {test_code_1}")
    else:
        LOGGER.info(f"Async test invitation code {test_code_1} already exists, skipping add.")

    inv = await sql_get_invitation_by_code(test_code_1)
    if inv:
        LOGGER.info(f"Retrieved async invitation: {inv}")
    else:
        LOGGER.error(f"Could not retrieve async invitation: {test_code_1}")

    test_invited_user = 200000002
    if inv and inv.status == 'pending':
        if await sql_mark_invitation_completed(test_code_1, test_invited_user):
            LOGGER.info(f"Successfully marked async {test_code_1} as completed by {test_invited_user}.")
        else:
            LOGGER.error(f"Failed to mark async {test_code_1} as completed.")
    elif inv:
        LOGGER.info(f"Async invitation {test_code_1} is already in status: {inv.status}")

    test_code_2 = "ASYNCTEST456"
    if not await sql_invitation_code_exists(test_code_2):
        await sql_add_invitation(test_code_2, test_inviter_1)
        await sql_mark_invitation_completed(test_code_2, 200000003)

    invite_count = await sql_get_successful_invites_count(test_inviter_1)
    LOGGER.info(f"Async inviter {test_inviter_1} has {invite_count} successful invites.")

    non_existent_code = "ASYNC_NONEXISTENT"
    if await sql_invitation_code_exists(non_existent_code):
        LOGGER.error(f"Async code {non_existent_code} reported as existing, but shouldn't.")
    else:
        LOGGER.info(f"Async code {non_existent_code} correctly reported as not existing.")

    LOGGER.info(f"Attempting to add duplicate async code {test_code_1} (expected failure)...")
    if not await sql_add_invitation(test_code_1, test_inviter_1 + 1):
        LOGGER.info("Successfully prevented adding duplicate async code.")
    else:
        LOGGER.error("Error: Allowed adding a duplicate async invitation code!")
        
    LOGGER.info(f"Attempting to mark already completed async code {test_code_1} (expected failure)...")
    if not await sql_mark_invitation_completed(test_code_1, 200000004):
        LOGGER.info("Successfully prevented marking an already completed async invitation.")
    else:
        LOGGER.error("Error: Allowed marking an already completed async invitation!")

    LOGGER.info("Async example usage finished.")

if __name__ == "__main__":
    # To run the async test:
    asyncio.run(_main_async_test())
