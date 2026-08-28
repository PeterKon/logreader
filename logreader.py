import PySimpleGUI as sg

from logreader_config import APP_VERSION, LogreaderConfig
from logreader_core import analyze_lines
from logreader_terminal import print_report, write_report

#Log analysis

#TODO: Migrate to different GUI (maybe)
#TODO: Add support for several files in at once (maybe)
#TODO: Fix general display_separator to be only initialized when has context and remove from GUI for both
#TODO: Change default filewrite to off
#TODO: Investigate error in custom pattern on browser log (lim non contxt 20 delimiter) (fix: conv to lower)
#TODO: Implement nested search (search from the generated error-lists with custom input)
#TODO: Catch and handle file-encoding errors (see file encodingtest)

def main():
    
    context = 3
    context_generic = 0
    
    display_separator = True
    display_separator_general = False
    write_to_file = True

    general_limit = 0

    version = APP_VERSION
    
    isFailedInitialized = True
    isFatalInitialized = True
    isWarningInitialized = False
    isFailureInitialized = False
    isIllegalInitialized = False
    isInvalidInitialized = False
    isExceptionInitialized = False
    isCriticalInitialized = False

    cust_pattern = ""
    cust_pattern2 = ""
    cust_pattern3 = ""
    
    #PySimpleGUI file-select
    layout = [[sg.T("")], 
        [sg.Text("Choose a logfile: "), 
            sg.Input(key="-IN2-" , change_submits=True), 
            sg.FileBrowse(key="-IN-")],
        [sg.Button("Submit")]]
    
    window = sg.Window(version, layout, size=(535,115))
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event=="Exit":
            break
        elif event == "Submit":
            filename = values["-IN-"]
            break
    
    #PySimpleGUI value-select  
    def_toggle_size = (21,1)
    def_box_size = (21,1)
    
    leftcol = [
        [sg.Text('')],
        [sg.Text(('Value Selection -'))],
        [sg.Text('')],
        [sg.Text(('Display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='SEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Write to file'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FILEWRITE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Output error limit:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='ERRIN', s=3),
            sg.Text("Default = Unlimited")],
        [sg.Text(('Context around errors:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='CONTIN', s=3),
            sg.Text("Default = 3")],
        [sg.Text('')],
        [sg.Text(('Custom pattern 1:'), size = def_box_size), sg.Input(key='CUSTOMIN', s=19)],
        [sg.Text(('Custom pattern 2:'), size = def_box_size), sg.Input(key='CUSTOMIN2', s=19)],
        [sg.Text(('Custom pattern 3:'), size = def_box_size), sg.Input(key='CUSTOMIN3', s=19)],
        [sg.Text('')],
        [sg.Text(('Generic display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='GENSEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('Generic context:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='GENCONTIN', s=3),
            sg.Text("Default = 0")],
        [sg.Text('')],
        [sg.Text('')],
        [sg.Text('')],
        [sg.Button("Submit")]
    ]
    
    rightcol = [
        [sg.Text('')],
        [sg.Text('Toggle Patterns -')],
        [sg.Text('')],
        [sg.Text(('Toggle All'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='TOGGLEALL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text('')],
        [sg.Text(('FAILED'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FAILED', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('FATAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FATAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('WARNING:'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='WARNING', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('FAILURE'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='FAILURE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('ILLEGAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='ILLEGAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('INVALID'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='INVALID', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('EXCEPTION:'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='EXCEPTION', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('CRITICAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='CRITICAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')]
    ]
    
    colSize = (360, 550)
    layout = [
        [sg.Column(leftcol, size=colSize),
        sg.VSeperator(),
        sg.Column(rightcol, size=colSize)]
    ]
    
    toggledOnce = False    
    window.close()    
    window = sg.Window(version, layout, size=(770,575))
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        elif event == 'SEPARATOR':
            window['SEPARATOR'].metadata = not window['SEPARATOR'].metadata
            window['SEPARATOR'].update(image_data=toggle_btn_on if window['SEPARATOR'].metadata else toggle_btn_off)
            display_separator = window['SEPARATOR'].metadata
        elif event == 'GENSEPARATOR':
            window['GENSEPARATOR'].metadata = not window['GENSEPARATOR'].metadata
            window['GENSEPARATOR'].update(image_data=toggle_btn_on if window['GENSEPARATOR'].metadata else toggle_btn_off)
            display_separator_general = window['GENSEPARATOR'].metadata
        elif event == 'FILEWRITE':
            window['FILEWRITE'].metadata = not window['FILEWRITE'].metadata
            window['FILEWRITE'].update(image_data=toggle_btn_on if window['FILEWRITE'].metadata else toggle_btn_off)
            write_to_file = window['FILEWRITE'].metadata
        elif event == 'TOGGLEALL':
            window['TOGGLEALL'].metadata = not window['TOGGLEALL'].metadata
            window['TOGGLEALL'].update(image_data=toggle_btn_on if window['TOGGLEALL'].metadata else toggle_btn_off)
            if not(toggledOnce):
                toggledOnce = True
            else:
                window['FAILED'].metadata = not window['FAILED'].metadata
                window['FAILED'].update(image_data=toggle_btn_on if window['FAILED'].metadata else toggle_btn_off)
                isFailedInitialized = window['FAILED'].metadata
                window['FATAL'].metadata = not window['FATAL'].metadata
                window['FATAL'].update(image_data=toggle_btn_on if window['FATAL'].metadata else toggle_btn_off)
                isFatalInitialized = window['FATAL'].metadata
            window['WARNING'].metadata = not window['WARNING'].metadata
            window['WARNING'].update(image_data=toggle_btn_on if window['WARNING'].metadata else toggle_btn_off)
            isWarningInitialized = window['WARNING'].metadata
            window['FAILURE'].metadata = not window['FAILURE'].metadata
            window['FAILURE'].update(image_data=toggle_btn_on if window['FAILURE'].metadata else toggle_btn_off)
            isFailureInitialized = window['FAILURE'].metadata
            window['ILLEGAL'].metadata = not window['ILLEGAL'].metadata
            window['ILLEGAL'].update(image_data=toggle_btn_on if window['ILLEGAL'].metadata else toggle_btn_off)
            isIllegalInitialized = window['ILLEGAL'].metadata
            window['INVALID'].metadata = not window['INVALID'].metadata
            window['INVALID'].update(image_data=toggle_btn_on if window['INVALID'].metadata else toggle_btn_off)
            isInvalidInitialized = window['INVALID'].metadata
            window['EXCEPTION'].metadata = not window['EXCEPTION'].metadata
            window['EXCEPTION'].update(image_data=toggle_btn_on if window['EXCEPTION'].metadata else toggle_btn_off)
            isExceptionInitialized = window['EXCEPTION'].metadata
            window['CRITICAL'].metadata = not window['CRITICAL'].metadata
            window['CRITICAL'].update(image_data=toggle_btn_on if window['CRITICAL'].metadata else toggle_btn_off)
            isCriticalInitialized = window['CRITICAL'].metadata
            
        elif event == 'FAILED':
            window['FAILED'].metadata = not window['FAILED'].metadata
            window['FAILED'].update(image_data=toggle_btn_on if window['FAILED'].metadata else toggle_btn_off)
            isFailedInitialized = window['FAILED'].metadata
        elif event == 'FATAL':
            window['FATAL'].metadata = not window['FATAL'].metadata
            window['FATAL'].update(image_data=toggle_btn_on if window['FATAL'].metadata else toggle_btn_off)
            isFatalInitialized = window['FATAL'].metadata
        elif event == 'WARNING':
            window['WARNING'].metadata = not window['WARNING'].metadata
            window['WARNING'].update(image_data=toggle_btn_on if window['WARNING'].metadata else toggle_btn_off)
            isWarningInitialized = window['WARNING'].metadata
        elif event == 'FAILURE':
            window['FAILURE'].metadata = not window['FAILURE'].metadata
            window['FAILURE'].update(image_data=toggle_btn_on if window['FAILURE'].metadata else toggle_btn_off)
            isFailureInitialized = window['FAILURE'].metadata
        elif event == 'ILLEGAL':
            window['ILLEGAL'].metadata = not window['ILLEGAL'].metadata
            window['ILLEGAL'].update(image_data=toggle_btn_on if window['ILLEGAL'].metadata else toggle_btn_off)
            isIllegalInitialized = window['ILLEGAL'].metadata
        elif event == 'INVALID':
            window['INVALID'].metadata = not window['INVALID'].metadata
            window['INVALID'].update(image_data=toggle_btn_on if window['INVALID'].metadata else toggle_btn_off)
            isInvalidInitialized = window['INVALID'].metadata
        elif event == 'EXCEPTION':
            window['EXCEPTION'].metadata = not window['EXCEPTION'].metadata
            window['EXCEPTION'].update(image_data=toggle_btn_on if window['EXCEPTION'].metadata else toggle_btn_off)
            isExceptionInitialized = window['EXCEPTION'].metadata
        elif event == 'CRITICAL':
            window['CRITICAL'].metadata = not window['CRITICAL'].metadata
            window['CRITICAL'].update(image_data=toggle_btn_on if window['CRITICAL'].metadata else toggle_btn_off)
            isCriticalInitialized = window['CRITICAL'].metadata
            
        elif event == 'CUSTOMIN':
            cust_pattern = values['CUSTOMIN']
        elif event == 'CUSTOMIN2':
            cust_pattern2 = values['CUSTOMIN2']
        elif event == 'CUSTOMIN3':
            cust_pattern3 = values['CUSTOMIN3']
            
        elif event == "Submit":
            display_separator = window['SEPARATOR'].metadata
            write_to_file = window['FILEWRITE'].metadata
            display_separator_general = window['GENSEPARATOR'].metadata
            cust_pattern = values['CUSTOMIN']
            cust_pattern2 = values['CUSTOMIN2']
            cust_pattern3 = values['CUSTOMIN3']
            isFailedInitialized = window['FAILED'].metadata
            isFatalInitialized = window['FATAL'].metadata
            isWarningInitialized = window['WARNING'].metadata
            isFailureInitialized = window['FAILURE'].metadata
            isIllegalInitialized = window['ILLEGAL'].metadata
            isInvalidInitialized = window['INVALID'].metadata
            isExceptionInitialized = window['EXCEPTION'].metadata
            isCriticalInitialized = window['CRITICAL'].metadata
            
            if values['GENCONTIN'] != '':
                context_generic = int(values['GENCONTIN'])            
            if values['ERRIN'] != '':
                general_limit = int(values['ERRIN'])
            if values['CONTIN'] != '':
                context = int(values['CONTIN'])                
            break
            
        elif event == 'ERRIN' and len(values['ERRIN']) and values['ERRIN'][-1] not in ('0123456789'):
            window['ERRIN'].update(values['ERRIN'][:-1])
        elif event == 'CONTIN' and len(values['CONTIN']) and values['CONTIN'][-1] not in ('0123456789'):
            window['CONTIN'].update(values['CONTIN'][:-1])
        elif event == 'GENCONTIN' and len(values['GENCONTIN']) and values['GENCONTIN'][-1] not in ('0123456789'):
            window['GENCONTIN'].update(values['GENCONTIN'][:-1])
    window.close()
    
    enabled_patterns = tuple(
        key
        for enabled, key in (
            (isFailedInitialized, "failed"),
            (isFatalInitialized, "fatal"),
            (isWarningInitialized, "warning"),
            (isFailureInitialized, "failure"),
            (isIllegalInitialized, "illegal"),
            (isInvalidInitialized, "invalid"),
            (isExceptionInitialized, "exception"),
            (isCriticalInitialized, "critical"),
        )
        if enabled
    )
    custom_patterns = tuple(
        pattern
        for pattern in (cust_pattern, cust_pattern2, cust_pattern3)
        if pattern
    )
    config = LogreaderConfig(
        context=context,
        generic_context=context_generic,
        limit=general_limit or None,
        enabled_patterns=enabled_patterns,
        custom_patterns=custom_patterns,
        show_separators=display_separator,
        show_generic_separators=display_separator_general,
    )

    with open(filename, "r") as log_file:
        logoutput = log_file.read().splitlines()

    analysis = analyze_lines(logoutput, config.search_patterns())
    print_report(filename, analysis, config, color=True)
    if write_to_file:
        write_report("outfile.txt", filename, analysis, config)

if __name__ == "__main__":

    toggle_btn_off = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAED0lEQVRYCe1WTWwbRRR+M/vnv9hO7BjHpElMKSlpqBp6gRNHxAFVcKM3qgohQSqoqhQ45YAILUUVDRxAor2VAweohMSBG5ciodJUSVqa/iikaePEP4nj2Ovdnd1l3qqJksZGXscVPaylt7Oe/d6bb9/svO8BeD8vA14GvAx4GXiiM0DqsXv3xBcJU5IO+RXpLQvs5yzTijBmhurh3cyLorBGBVokQG9qVe0HgwiXLowdy9aKsY3g8PA5xYiQEUrsk93JTtjd1x3siIZBkSWQudUK4nZO1w3QuOWXV+HuP/fL85klAJuMCUX7zPj4MW1zvC0Ej4yMp/w++K2rM9b70sHBYCjo34x9bPelsgp/XJksZ7KFuwZjr3732YcL64ttEDw6cq5bVuCvgy/sje7rT0sI8PtkSHSEIRIKgCQKOAUGM6G4VoGlwiqoVd2Za9Vl8u87bGJqpqBqZOj86eEHGNch+M7otwHJNq4NDexJD+59RiCEQG8qzslFgN8ibpvZNsBifgXmFvJg459tiOYmOElzYvr2bbmkD509e1ylGEZk1Y+Ssfan18n1p7vgqVh9cuiDxJPxKPT3dfGXcN4Tp3dsg/27hUQs0qMGpRMYjLz38dcxS7Dm3nztlUAb38p0d4JnLozPGrbFfBFm79c8hA3H2AxcXSvDz7/+XtZE1kMN23hjV7LTRnKBh9/cZnAj94mOCOD32gi2EUw4FIRUMm6LGhyiik86nO5NBdGRpxYH14bbjYfJteN/OKR7UiFZVg5T27QHYu0RBxoONV9W8KQ7QVp0iXdE8fANUGZa0QAvfhhXlkQcmjJZbt631oIBnwKmacYoEJvwiuFgWncWnXAtuVBBEAoVVXWCaQZzxmYuut68b631KmoVBEHMUUrJjQLXRAQVSxUcmrKVHfjWWjC3XOT1FW5QrWpc5IJdQhDKVzOigEqS5dKHMVplnNOqrmsXqUSkn+YzWaHE9RW1FeXL7SKZXBFUrXW6jIV6YTEvMAUu0W/G3kcxPXP5ylQZs4fa6marcWvvZfJu36kuHjlc/nMSuXz+/ejxgqPFpuQ/xVude9eu39Jxu27OLvBGoMjrUN04zrNMbgVmOBZ96iPdPZmYntH5Ls76KuxL9NyoLA/brav7n382emDfHqeooXyhQmARVhSnAwNNMx5bu3V1+habun5nWdXhwJZ2C5mirTesyUR738sv7g88UQ0rEkTDlp+1wwe8Pf0klegUenYlgyg7bby75jUTITs2rhCAXXQ2vwxz84vlB0tZ0wL4NEcLX/04OrrltG1s8aOrHhk51SaK0us+n/K2xexBxljcsm1n6x/Fuv1PCWGiKOaoQCY1Vb9gWPov50+fdEqd21ge3suAlwEvA14G/ucM/AuppqNllLGPKwAAAABJRU5ErkJggg=='
    toggle_btn_on = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAD+UlEQVRYCe1XzW8bVRCffbvrtbP+2NhOD7GzLm1VoZaPhvwDnKBUKlVyqAQ3/gAkDlWgPeVQEUCtEOIP4AaHSI0CqBWCQyXOdQuRaEFOk3g3IMWO46+tvZ+PeZs6apq4ipON1MNafrvreTPzfvub92bGAOEnZCBkIGQgZOClZoDrh25y5pdjruleEiX+A+rCaQo05bpuvJ/+IHJCSJtwpAHA/e269g8W5RbuzF6o7OVjF8D3Pr4tSSkyjcqfptPDMDKSleW4DKIggIAD5Yf+Oo4DNg6jbUBlvWLUNutAwZu1GnDjzrcXzGcX2AHw/emFUV6Sfk0pqcKpEydkKSo9q3tkz91uF5aWlo1Gs/mYc+i7tz4//19vsW2AU9O381TiioVCQcnlRsWeQhD3bJyH1/MiFLICyBHiuzQsD1arDvypW7DR9nzZmq47q2W95prm+I9fXfqXCX2AF2d+GhI98Y8xVX0lnxvl2UQQg0csb78ag3NjEeD8lXZ7pRTgftmCu4864OGzrq+5ZU0rCa3m+NzXlzvoAoB3+M+SyWQuaHBTEzKMq/3BMbgM+FuFCDBd9kK5XI5PJBKqLSev+POTV29lKB8rT0yMD0WjUSYLZLxzNgZvIHODOHuATP72Vwc6nQ4Uiw8MUeBU4nHS5HA6TYMEl02wPRcZBJuv+ya+UCZOIBaLwfCwQi1Mc4QXhA+PjWRkXyOgC1uIhW5Qd8yG2TK7kSweLcRGKKVnMNExWWBDTQsH9qVmtmzjiThQDs4Qz/OUSGTwcLwIQTLW58i+yOjpXDLqn1tgmDzXzRCk9eDenjo9yhvBmlizrB3V5dDrNTuY0A7opdndStqmaQLPC1WCGfShYRgHdLe32UrV3ntiH9LliuNrsToNlD4kruN8v75eafnSgC6Luo2+B3fGKskilj5muV6pNhk2Qqg5v7lZ51nBZhNBjGrbxfI1+La5t2JCzfD8RF1HTBGJXyDzs1MblONulEqPDVYXgwDIfNx91IUVbAbY837GMur+/k/XZ75UWmJ77ou5mfM1/0x7vP1ls9XQdF2z9uNsPzosXPNFA5m0/EX72TBSiqsWzN8z/GZB08pWq9VeEZ+0bjKb7RTD2i1P4u6r+bwypo5tZUumEcDAmuC3W8ezIqSGfE6g/sTd1W5p5bKjaWubrmWd29Fu9TD0GlYlmTx+8tTJoZeqYe2BZC1/JEU+wQR5TVEUPptJy3Fs+Vkzgf8lemqHumP1AnYoMZSwsVEz6o26i/G9Lgitb+ZmLu/YZtshfn5FZDPBCcJFQRQ+8ih9DctOFvdLIKHH6uUQnq9yhFu0bec7znZ+xpAGmuqef5/wd8hAyEDIQMjAETHwP7nQl2WnYk4yAAAAAElFTkSuQmCC'

    main()
