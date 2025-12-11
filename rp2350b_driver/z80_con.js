s_portCache = "";

API.writePort = (port, value) => {
    if (port == 0xff83) {
        const ch = String.fromCharCode(value);
        API.log(ch);
        //s_portCache += ch;
        //if (ch == '\x0a') {
        //    API.log(s_portCache);
        //    s_portCache = "";
        //}

        //console.log("HELLO_FROM_CUSTOM_CODE: " + String.fromCharCode(value));//`zsim port: ${value}`);
    }
}