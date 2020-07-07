#! /bin/sh
#
# Perform update, keep state in file system.
#
# Exit codes:
#    0  Done, no errors
#    3  Tried to run this template script directly
#    5  The update plan does not exist
#    6  Status file directory does not exist
#    7  Bad state.
#   10  Update step failed (first try)
#   11  Update step failed (second try)
#   12  Update not attempted again due to previous multiple failures (most
#       probably a recovery is needed)
#   20  Reboot step failed for some reason
#   21  Reboot step failed because the reboot request failed
#
# State files (maintained in @STAMP_DIR@) are documented in states.md, the
# associated states are documented in states.dot.
#

test "x@ALLOW_EXECUTION@" = "xyes" || exit 3

THE_PLAN="@THE_PLAN@"
STAMP_DIR="@STAMP_DIR@"

test -f "${THE_PLAN}" || exit 5
test -d "${STAMP_DIR}" || exit 6

UPDATE_FINISHED="${STAMP_DIR}/update_finished"
UPDATE_BEGIN="${STAMP_DIR}/update_started"
UPDATE_DONE="${STAMP_DIR}/update_done"
UPDATE_FAIL="${STAMP_DIR}/update_failure"
UPDATE_FAIL_AGAIN="${STAMP_DIR}/update_failure_again"
UPDATE_EXIT_CODE="${STAMP_DIR}/update_exit_code"
REBOOT_BEGIN="${STAMP_DIR}/update_reboot_started"
REBOOT_STATUS="${STAMP_DIR}/update_reboot_stderr"
REBOOT_FAIL="${STAMP_DIR}/update_reboot_failed"
REBOOT_EXIT_CODE="${STAMP_DIR}/update_reboot_exit_code"

test -f "${UPDATE_FINISHED}" && exit 0

# determine state and clean up stamp files (just in case)
if test ! -f "${UPDATE_BEGIN}"
then
    STATE='init'
    rm -f "${UPDATE_BEGIN}" "${UPDATE_DONE}" "${UPDATE_FAIL}" \
          "${UPDATE_FAIL_AGAIN}" "${REBOOT_BEGIN}" "${REBOOT_STATUS}" \
          "${REBOOT_FAIL}"
elif test -f "${UPDATE_DONE}"
then
    rm -f "${UPDATE_FAIL}" "${UPDATE_FAIL_AGAIN}"
    if test ! -f "${REBOOT_BEGIN}"
    then
        STATE='US'
        rm -f "${REBOOT_STATUS}" "${REBOOT_FAIL}"
    elif test ! -f "${REBOOT_STATUS}"
    then
        STATE='UR'
        rm -f "${REBOOT_FAIL}"
    elif test -f "${REBOOT_FAIL}"
    then
        STATE='URF'
    else
        # this is actually UR2, but at startup it is C
        STATE='C'
    fi
elif test -f "${UPDATE_FAIL}"
then
    if test -f "${UPDATE_FAIL_AGAIN}"
    then
        STATE='RF'
        rm -f "${REBOOT_BEGIN}" "${REBOOT_STATUS}" "${REBOOT_FAIL}"
    elif test ! -f "${REBOOT_BEGIN}"
    then
        STATE='UF'
        rm -f "${REBOOT_STATUS}" "${REBOOT_FAIL}"
    elif test ! -f "${REBOOT_STATUS}"
    then
        STATE='FR'
        rm -f "${REBOOT_FAIL}"
    elif test -f "${REBOOT_FAIL}"
    then
        STATE='FRF'
    else
        # this is actually FR2, but at startup it is R
        STATE='R'
    fi
else
    STATE='U'
    rm -f "${UPDATE_FAIL_AGAIN}" "${REBOOT_BEGIN}" "${REBOOT_STATUS}" \
          "${REBOOT_FAIL}"
fi

IS_FIRST_STATE=1

# process state machine
while true
do
    case $STATE
    in
        init)
            STATE='U'
            touch "${UPDATE_BEGIN}"
            ;;
        U)
            logger 'Starting update'
            rm -f "${UPDATE_EXIT_CODE}"

            updata_execute.py --avoid-reboot -p "${THE_PLAN}" 2>"${UPDATE_FAIL}"
            RET=$?

            if test ${RET} -eq 0
            then
                STATE='US'
                rm -f "${UPDATE_FAIL}"
                touch "${UPDATE_DONE}"
            else
                STATE='UF'
                echo "${RET}" >"${UPDATE_EXIT_CODE}"
            fi
            ;;
        R)
            logger 'Resuming update'
            rm -f "${UPDATE_FAIL}" "${REBOOT_BEGIN}" "${REBOOT_STATUS}" \
                  "${UPDATE_EXIT_CODE}"

            updata_execute.py --avoid-reboot -p "${THE_PLAN}" 2>"${UPDATE_FAIL}"
            RET=$?

            if test ${RET} -eq 0
            then
                STATE='US'
                rm -f "${UPDATE_FAIL}" "${UPDATE_FAIL_AGAIN}"
                touch "${UPDATE_DONE}"
            else
                STATE='RF'
                echo "${RET}" >"${UPDATE_EXIT_CODE}"
                touch "${UPDATE_FAIL_AGAIN}"
            fi
            ;;
        US)
            STATE='UR'
            touch "${REBOOT_BEGIN}"
            ;;
        UR)
            rm -f "${REBOOT_EXIT_CODE}"

            updata_execute.py --reboot-only -p "${THE_PLAN}" 2>"${REBOOT_STATUS}"
            RET=$?

            if test ${RET} -eq 0
            then
                STATE='UR2'
            else
                # failed to reboot
                STATE='URF'
                touch "${REBOOT_FAIL}"
                echo "${RET}" >"${REBOOT_EXIT_CODE}"
            fi
            ;;
        UR2)
            logger 'Rebooting for completion'
            exit 0
            ;;
        C)
            logger 'Update finished'
            touch "${UPDATE_FINISHED}"
            exit 0
            ;;
        URF)
            if test -f "${REBOOT_EXIT_CODE}"
            then
                read -r RET <"${REBOOT_EXIT_CODE}"
                test -n "${RET}" || RET=10
            else
                RET=10
            fi

            if test -s "${REBOOT_STATUS}"
            then
                logger <"${REBOOT_STATUS}"
            else
                logger "Failed executing reboot step: exit code ${RET}, no error messages"
            fi

            test ${RET} -eq 10 || exit 20
            exit 21
            ;;
        UF)
            if test -f "${UPDATE_EXIT_CODE}"
            then
                read -r RET <"${UPDATE_EXIT_CODE}"
                test -n "${RET}" || RET='empty'
            else
                RET='unknown'
            fi

            if test -s "${UPDATE_FAIL}"
            then
                logger <"${UPDATE_FAIL}"
            else
                logger "Failed update plan execution: exit code ${RET}, no error messages"
            fi

            STATE='FR'
            touch "${REBOOT_BEGIN}"
            ;;
        RF)
            if test -f "${UPDATE_EXIT_CODE}"
            then
                read -r RET <"${UPDATE_EXIT_CODE}"
                test -n "${RET}" || RET='empty'
            else
                RET='unknown'
            fi

            if test -s "${UPDATE_FAIL}"
            then
                logger <"${UPDATE_FAIL}"
            else
                logger "Failed update plan execution: exit code ${RET}, no error messages"
            fi

            logger "Failed AGAIN, giving up"
            test ${IS_FIRST_STATE} -ne 0 || exit 11
            exit 12
            ;;
        FR)
            rm -f "${REBOOT_EXIT_CODE}"

            updata_execute.py --reboot-only -p "${THE_PLAN}" 2>"${REBOOT_STATUS}"
            RET=$?

            if test ${RET} -eq 0
            then
                STATE='FR2'
            else
                # failed to reboot
                STATE='FRF'
                touch "${REBOOT_FAIL}"
                echo "${RET}" >"${REBOOT_EXIT_CODE}"
            fi
            ;;
        FR2)
            test ${IS_FIRST_STATE} -ne 0 || logger 'Rebooting to resume after error'
            exit 0
            ;;
        FRF)
            if test -f "${REBOOT_EXIT_CODE}"
            then
                read -r RET <"${REBOOT_EXIT_CODE}"
                test -n "${RET}" || RET=10
            else
                RET=10
            fi

            if test -s "${REBOOT_STATUS}"
            then
                logger <"${REBOOT_STATUS}"
            else
                logger "Failed executing reboot step: exit code ${RET}, no error messages"
            fi

            test ${RET} -eq 10 || exit 20
            exit 21
            ;;
        *)
            logger "BAD STATE \"${STATE}"\"
            exit 7
            ;;
    esac

    IS_FIRST_STATE=0
done
