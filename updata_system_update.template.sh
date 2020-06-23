#! /bin/sh
#
# Perform update, keep state in file system.
#
# Exit codes:
#    0  Done, no errors
#    3  Tried to run this template script directly
#    5  The update plan does not exist
#    6  Status file directory does not exist
#   10  Update step failed (first try)
#   11  Update step failed (second try)
#   12  Update not attempted again due to previous multiple failures (most
#       probably a recovery is needed)
#   20  Reboot step failed for some reason
#   21  Reboot step failed because the reboot request failed
#
# State files (maintained in @STAMP_DIR@):
#   update_started
#   update_done
#   update_failure
#   update_failure_again
#   update_reboot_started
#   update_reboot_stderr
#   update_reboot_failed
#   update_try_restart
#

test "x@ALLOW_EXECUTION@" = "xyes" || exit 3

THE_PLAN="@THE_PLAN@"
STAMP_DIR="@STAMP_DIR@"

test -f "${THE_PLAN}" || exit 5
test -d "${STAMP_DIR}" || exit 6

UPDATE_BEGIN="${STAMP_DIR}/update_started"
UPDATE_DONE="${STAMP_DIR}/update_done"
UPDATE_FAIL="${STAMP_DIR}/update_failure"
UPDATE_FAIL_AGAIN="${STAMP_DIR}/update_failure_again"
REBOOT_BEGIN="${STAMP_DIR}/update_reboot_started"
REBOOT_STATUS="${STAMP_DIR}/update_reboot_stderr"
REBOOT_DONE="${STAMP_DIR}/update_reboot_done"
REBOOT_FAIL="${STAMP_DIR}/update_reboot_failed"
UPDATE_TRY_RESTART="${STAMP_DIR}/update_try_restart"

test -f "${UPDATE_DONE}" || rm -f "${UPDATE_BEGIN}"
test -f "${REBOOT_FAIL}" || rm -f "${REBOOT_BEGIN}"

test -f "${UPDATE_FAIL_AGAIN}" && exit 12

if test -f "${UPDATE_BEGIN}" || test -f "${UPDATE_TRY_RESTART}"
then
    if test -f "${UPDATE_FAIL}"
    then
        touch "${UPDATE_FAIL_AGAIN}"
        rm -f "${UPDATE_BEGIN}" "${UPDATE_TRY_RESTART}"
    fi
fi

if test ! -f "${UPDATE_BEGIN}"
then
    rm -f "${UPDATE_DONE}" "${UPDATE_FAIL}" "${REBOOT_BEGIN}"
    rm -f "${REBOOT_DONE}" "${REBOOT_STATUS}" "${REBOOT_FAIL}"
    touch "${UPDATE_BEGIN}"
    sync

    updata_execute.py --avoid-reboot -p "${THE_PLAN}" 2>"${UPDATE_FAIL}"
    RET=$?

    # we are done with the update step
    touch "${UPDATE_DONE}"

    if test ${RET} -ne 0
    then
        if test -s "${UPDATE_FAIL}"
        then
            logger <"${UPDATE_FAIL}"
        else
            logger "Failed update plan execution: exit code ${RET}, but no error messages"
        fi

        test -f "${UPDATE_FAIL_AGAIN}" && exit 11
        exit 10
    fi

    # no error: remove the failure markers
    rm -f "${UPDATE_FAIL}" "${UPDATE_FAIL_AGAIN}"
fi

if test ! -f "${REBOOT_BEGIN}"
then
    touch "${REBOOT_BEGIN}"
    sync

    updata_execute.py --reboot-only -p "${THE_PLAN}" 2>"${REBOOT_STATUS}"
    RET=$?

    # reboot was possibly triggered, therefore it is possible (though unlikely)
    # that we do not reach this point in case the script returned with no
    # error; in case of no error, we simply create a final file and terminate
    if test ${RET} -eq 0
    then
        touch "${REBOOT_DONE}"
        exit 0
    fi

    # failed to reboot
    if test -s "${REBOOT_STATUS}"
    then
        logger <"${REBOOT_STATUS}"
    else
        logger "Failed executing reboot step: exit code ${RET}, but no error messages"
    fi

    touch "${REBOOT_FAIL}"

    test ${RET} -eq 10 || exit 20
    exit 21
else
    touch "${REBOOT_DONE}"
fi

exit 0
